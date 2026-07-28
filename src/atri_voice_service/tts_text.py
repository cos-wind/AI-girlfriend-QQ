from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_ENTRIES = (
    {"source": "ATRI", "zh": "亚托莉", "en": "Atri", "ja": "アトリ"},
    {"source": "GPT-SoVITS", "zh": "GPT SoVITS", "en": "GPT So VITS", "ja": "ジーピーティー ソヴィッツ"},
    {"source": "NapCat", "zh": "Nap Cat", "en": "Nap Cat", "ja": "ナップキャット"},
    {"source": "QQ", "zh": "Q Q", "en": "Q Q", "ja": "キューキュー"},
)

_STAGE_DIRECTION_CUES = (
    "轻声",
    "小声",
    "低声",
    "柔声",
    "压低声音",
    "提高声音",
    "语气",
    "语调",
    "调子",
    "带着",
    "笑着",
    "微笑",
    "叹气",
    "停顿",
    "认真地",
    "温柔地",
    "开心地",
    "难过地",
    "害羞地",
    "惊讶地",
    "困倦地",
    "撒娇",
    "哭腔",
    "清嗓",
    "讲故事",
)


@dataclass(frozen=True)
class PronunciationEntry:
    source: str
    replacements: dict[str, str]


class TtsPronunciationLexicon:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._mtime_ns: int | None = None
        self._entries: tuple[PronunciationEntry, ...] = ()

    @property
    def entries(self) -> tuple[PronunciationEntry, ...]:
        self._reload_if_changed()
        return self._entries

    def terms(self) -> list[str]:
        return [entry.source for entry in self.entries]

    def apply(self, text: str, language: str) -> str:
        resolved_language = _dominant_language(text) if language == "auto" else language
        result = text
        for entry in sorted(self.entries, key=lambda item: len(item.source), reverse=True):
            replacement = (
                entry.replacements.get(resolved_language)
                or entry.replacements.get("zh")
                or entry.source
            )
            flags = re.IGNORECASE if entry.source.isascii() else 0
            result = re.sub(re.escape(entry.source), replacement, result, flags=flags)
        return result

    def _reload_if_changed(self) -> None:
        if not self.path.is_file():
            save_pronunciations(self.path, list(DEFAULT_ENTRIES))
        mtime_ns = self.path.stat().st_mtime_ns
        if self._mtime_ns == mtime_ns:
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        raw_entries = payload.get("entries", []) if isinstance(payload, dict) else []
        self._entries = tuple(
            PronunciationEntry(
                source=item["source"],
                replacements={language: item[language] for language in ("zh", "en", "ja")},
            )
            for item in _normalized_entries(raw_entries)
        )
        self._mtime_ns = mtime_ns


def normalize_tts_text(text: str, language: str) -> str:
    value = html.unescape(str(text or ""))
    value = re.sub(r"```.*?```", " ", value, flags=re.DOTALL)
    value = re.sub(r"[*_~`#]+", "", value)
    value = _remove_stage_directions(value)
    value = re.sub(r"[～〜~]+(?=\s*$)", "。", value)
    value = re.sub(r"[～〜~]+", "，", value)
    value = re.sub(r"(?:…{1,}|\.{3,})", "，", value)
    value = re.sub(r"[—–]+", "，", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = "".join(
        char
        for char in value
        if unicodedata.category(char) not in {"Cs", "Co"}
        and not (
            unicodedata.category(char) == "So"
            and char not in {"。", "！", "？", "…"}
        )
    ).strip()
    value = re.sub(r"\s+([,，.!！？?。…])", r"\1", value)
    value = re.sub(r"([,，.!！？?。…])\s+", r"\1", value)
    value = re.sub(r"([!?！？。])\1+", r"\1", value)
    value = re.sub(r"([，,。])(?:\s*[，,。])+", r"\1", value)
    value = _shape_spoken_prosody(value, language)
    if value and value[-1] not in "。！？!?.,，…":
        value += "。" if language in {"zh", "ja", "auto"} else "."
    return value


def _shape_spoken_prosody(text: str, language: str) -> str:
    if language not in {"zh", "auto"}:
        return text
    value = re.sub(
        r"^(这样的话|那就好|好啦|好呀|当然|不过|所以|那么|对了|"
        r"嗯|唔|诶|哎)\s*(?=[\u3400-\u9fffA-Za-z0-9])",
        r"\1，",
        text,
    )
    return re.sub(
        r"^(主人|大家|你们)\s*(?=[\u3400-\u9fffA-Za-z0-9])",
        r"\1，",
        value,
    )


def _remove_stage_directions(text: str) -> str:
    pattern = re.compile(
        r"[\(（\[【]\s*(?P<direction>[^\)）\]】]{1,80})\s*[\)）\]】]"
    )

    def replace_direction(match: re.Match[str]) -> str:
        direction = match.group("direction")
        return " " if any(cue in direction for cue in _STAGE_DIRECTION_CUES) else match.group(0)

    return pattern.sub(replace_direction, text)


def load_pronunciation_text(path: Path) -> str:
    lexicon = TtsPronunciationLexicon(path)
    return "\n".join(
        f"{entry.source} = {entry.replacements['zh']} | "
        f"{entry.replacements['en']} | {entry.replacements['ja']}"
        for entry in lexicon.entries
    )


def save_pronunciation_text(path: Path, text: str) -> dict[str, Any]:
    entries: list[dict[str, str]] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        source, separator, raw_replacements = line.partition("=")
        if not separator:
            continue
        values = [part.strip() for part in raw_replacements.split("|")]
        if len(values) != 3:
            raise ValueError(f"发音词典格式错误：{line}")
        entries.append(
            {"source": source.strip(), "zh": values[0], "en": values[1], "ja": values[2]}
        )
    return save_pronunciations(path, entries)


def save_pronunciations(path: Path, entries: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = _normalized_entries(entries)
    payload = {"version": 1, "entries": normalized}
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return payload


def _normalized_entries(entries: Any) -> list[dict[str, str]]:
    if not isinstance(entries, list):
        raise ValueError("发音词典必须是列表")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        source = re.sub(r"\s+", " ", str(item.get("source") or "")).strip()
        if not source or len(source) > 60 or source.casefold() in seen:
            continue
        values = {
            language: re.sub(r"\s+", " ", str(item.get(language) or source)).strip()
            for language in ("zh", "en", "ja")
        }
        if any(not value or len(value) > 100 for value in values.values()):
            continue
        seen.add(source.casefold())
        normalized.append({"source": source, **values})
        if len(normalized) >= 100:
            break
    return normalized


def _dominant_language(text: str) -> str:
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    return "en"
