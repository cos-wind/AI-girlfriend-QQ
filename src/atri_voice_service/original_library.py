from __future__ import annotations

import hashlib
import re
import shutil
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path


AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".ogg", ".m4a", ".aac", ".opus"}
LANGUAGE_ALIASES = {
    "cn": "zh",
    "zh": "zh",
    "jp": "ja",
    "ja": "ja",
    "en": "en",
}
SEMANTIC_CLIP_ALIASES = (
    frozenset({"早安", "早上好"}),
)
CONTEXTUAL_CUE_GROUPS = (
    (
        ("早上好",),
        ("早上好", "早安", "上午好", "早啊", "早呀", "goodmorning", "おはよう"),
        0.93,
    ),
    (
        ("再见",),
        ("再见", "拜拜", "回头见", "晚点见", "下次见", "goodbye", "seeyou", "さようなら", "またね"),
        0.92,
    ),
    (
        ("不可以看",),
        ("不可以看", "别看", "不要看", "不许看", "不能看", "dontlook", "donotlook", "見ないで"),
        0.91,
    ),
    (
        ("不要来回来去地摸",),
        ("别摸", "不要摸", "不许摸", "一直摸", "来回摸", "donttouch", "stoptouching", "触らないで"),
        0.9,
    ),
    (("疼",), ("疼", "好痛", "痛死", "受伤", "ouch", "hurts", "痛い"), 0.9),
    (
        ("派上用场",),
        ("派上用场", "帮上忙", "帮到你", "有用了", "完成任务", "做好了", "helped", "useful", "役に立った"),
        0.89,
    ),
    (("高性能",), ("高性能", "厉害吧", "能干吧", "highperformance"), 0.88),
    (("搞砸",), ("搞砸", "做错", "失败了", "出错", "又错了", "messedup", "failed", "失敗", "やらかした"), 0.88),
    (("机器人怎么会明白",), ("不明白", "不懂", "机器人", "无法理解", "robot", "ロボット", "わからない"), 0.87),
    (("终于被放过",), ("放过我", "终于结束", "终于好了", "finallyfree", "やっと", "終わった"), 0.87),
    (("羡慕",), ("羡慕", "嫉妒", "吃醋", "jealous", "羨ましい", "嫉妬"), 0.88),
    (("螃蟹",), ("螃蟹", "是蟹", "什么蟹", "crab", "カニ"), 0.92),
    (("有的",), ("有吗", "有么", "有没有", "当然有", "doyouhave", "ありますか"), 0.87),
    (("盯",), ("盯着", "看着你", "注视", "stare", "watching", "じー"), 0.84),
)


@dataclass(frozen=True)
class OriginalClip:
    path: Path
    transcript: str
    language: str
    score: float = 1.0
    source: str = "library"


class OriginalVoiceLibrary:
    def __init__(
        self,
        root: Path,
        cache_dir: Path,
        *,
        refresh_seconds: float = 60.0,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.cache_dir = Path(cache_dir).expanduser().resolve() / "original-clips"
        self.refresh_seconds = max(1.0, float(refresh_seconds))
        self._clips: tuple[OriginalClip, ...] = ()
        self._singing_paths: tuple[Path, ...] = ()
        self._last_scan_at = 0.0
        self._last_error = ""

    def status(self) -> dict[str, object]:
        self._refresh_if_needed()
        return {
            "root": str(self.root),
            "available": self.root.is_dir(),
            "clips": len(self._clips),
            "handcrafted_clips": sum(
                clip.source == "handcrafted" for clip in self._clips
            ),
            "last_error": self._last_error,
        }

    def singing_count(self) -> int:
        return len(self.singing_references())

    def singing_references(self) -> list[dict[str, str]]:
        """Return the canonical singing-reference list for every local client."""

        self._refresh_if_needed()
        references: list[dict[str, str]] = []
        for resolved in self._singing_paths:
            relative = resolved.relative_to(self.root)
            reference_id = hashlib.sha256(
                relative.as_posix().encode("utf-8")
            ).hexdigest()[:12]
            references.append(
                {
                    "id": reference_id,
                    "name": resolved.stem,
                    "path": str(resolved),
                    "relative_path": str(relative),
                }
            )
        return references

    def match(
        self,
        text: str,
        language: str = "auto",
        *,
        minimum_score: float = 0.94,
        singing_only: bool = False,
    ) -> OriginalClip | None:
        self._refresh_if_needed()
        expected = normalize_clip_text(text)
        if not expected:
            return None
        requested_language = str(language or "auto").lower()
        best: OriginalClip | None = None
        for clip in self._clips:
            if singing_only and not _is_singing_path(clip.path, self.root):
                continue
            if requested_language not in {"", "auto"} and clip.language not in {
                "auto",
                requested_language,
            }:
                continue
            actual = normalize_clip_text(clip.transcript)
            if not actual:
                continue
            score = 1.0 if actual == expected else SequenceMatcher(None, expected, actual).ratio()
            score = max(score, _semantic_alias_score(expected, actual))
            if clip.source == "handcrafted":
                score = max(score, _handcrafted_context_score(expected, actual))
            if score < minimum_score:
                continue
            candidate = OriginalClip(
                clip.path,
                clip.transcript,
                clip.language,
                score,
                clip.source,
            )
            if best is None or _match_rank(candidate) > _match_rank(best):
                best = candidate
        return best

    def materialize(self, clip: OriginalClip) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(str(clip.path).encode("utf-8")).hexdigest()[:20]
        target = self.cache_dir / f"{digest}{clip.path.suffix.lower()}"
        if not target.is_file() or target.stat().st_mtime_ns < clip.path.stat().st_mtime_ns:
            temporary = target.with_suffix(target.suffix + ".tmp")
            shutil.copy2(clip.path, temporary)
            temporary.replace(target)
        return target

    def match_contextual(
        self,
        text: str,
        language: str = "auto",
        *,
        minimum_score: float = 0.8,
    ) -> OriginalClip | None:
        """Find an intent-level fallback from user-curated official clips."""

        self._refresh_if_needed()
        expected = normalize_clip_text(text)
        if not expected:
            return None
        best: OriginalClip | None = None
        for clip in self._clips:
            if clip.source != "handcrafted":
                continue
            actual = normalize_clip_text(clip.transcript)
            score = _contextual_fallback_score(expected, actual)
            if score < minimum_score:
                continue
            candidate = OriginalClip(
                clip.path,
                clip.transcript,
                clip.language,
                score,
                clip.source,
            )
            if best is None or _match_rank(candidate) > _match_rank(best):
                best = candidate
        return best

    def _refresh_if_needed(self) -> None:
        now = time.monotonic()
        if self._clips and now - self._last_scan_at < self.refresh_seconds:
            return
        self._last_scan_at = now
        try:
            self._clips = tuple(_scan_clips(self.root))
            self._singing_paths = tuple(_scan_singing_paths(self.root))
            self._last_error = ""
        except OSError as exc:
            self._last_error = str(exc)


def _semantic_alias_score(expected: str, actual: str) -> float:
    for aliases in SEMANTIC_CLIP_ALIASES:
        if expected in aliases and actual in aliases:
            return 0.985
    return 0.0


def normalize_clip_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(char for char in value if char.isalnum())


def _scan_clips(root: Path) -> list[OriginalClip]:
    if not root.is_dir():
        return []
    clips: list[OriginalClip] = []
    labelled_paths: set[Path] = set()
    for label_file in root.rglob(".speaker.list"):
        for line in label_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            parts = line.strip().split("|", 3)
            if len(parts) != 4:
                continue
            raw_path, _speaker, raw_language, transcript = parts
            path = (label_file.parent / raw_path).resolve()
            if not path.is_file():
                path = (label_file.parent / Path(raw_path).name).resolve()
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            labelled_paths.add(path)
            clips.append(
                OriginalClip(
                    path=path,
                    transcript=transcript.strip(),
                    language=LANGUAGE_ALIASES.get(raw_language.strip().lower(), "auto"),
                    source=_clip_source(path, root),
                )
            )
    for path in root.rglob("*"):
        resolved = path.resolve()
        if (
            not path.is_file()
            or path.suffix.lower() not in AUDIO_EXTENSIONS
            or resolved in labelled_paths
        ):
            continue
        transcript = _filename_transcript(path.stem)
        if transcript:
            clips.append(
                OriginalClip(
                    path=resolved,
                    transcript=transcript,
                    language=_guess_language(transcript),
                    source=_clip_source(resolved, root),
                )
            )
    return clips


def _scan_singing_paths(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        (
            path.resolve()
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in AUDIO_EXTENSIONS
            and _is_singing_path(path, root)
        ),
        key=lambda path: str(path).casefold(),
    )


def _filename_transcript(stem: str) -> str:
    value = re.sub(r"^[A-Za-z]{2,8}[_-][A-Za-z0-9_-]+$", "", stem).strip()
    value = re.sub(r"^\d+[_-]", "", value).strip()
    normalized = normalize_clip_text(value)
    if len(normalized) >= 2 or re.fullmatch(r"[\u3040-\u30ff\u4e00-\u9fff]", normalized):
        return value
    return ""


def _guess_language(text: str) -> str:
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return "auto"


def _clip_source(path: Path, root: Path) -> str:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return (
        "handcrafted"
        if any("手搓音频素材" in part for part in parts)
        else "library"
    )


def _handcrafted_context_score(expected: str, actual: str) -> float:
    if not actual or actual not in expected:
        return 0.0
    extra = len(expected) - len(actual)
    if len(actual) >= 4 and extra <= max(4, len(actual)):
        return 0.965
    if len(actual) >= 3 and extra <= 3:
        return 0.955
    return 0.0


def _contextual_fallback_score(expected: str, actual: str) -> float:
    if not expected or not actual:
        return 0.0
    score = max(
        _semantic_alias_score(expected, actual),
        SequenceMatcher(None, expected, actual).ratio(),
    )
    if actual in expected and len(actual) >= 3:
        coverage = len(actual) / max(1, len(expected))
        score = max(score, min(0.94, 0.79 + coverage * 0.2))
    for clip_cues, request_cues, cue_score in CONTEXTUAL_CUE_GROUPS:
        if any(cue in actual for cue in clip_cues) and any(
            cue in expected for cue in request_cues
        ):
            score = max(score, cue_score)
    return score


def _match_rank(clip: OriginalClip) -> tuple[int, float]:
    source_priority = 1 if clip.source == "handcrafted" else 0
    return source_priority, clip.score


def _is_singing_path(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(
        marker in part.casefold()
        for part in parts
        for marker in ("歌唱", "唱歌", "singing", "song", "vocal")
    )
