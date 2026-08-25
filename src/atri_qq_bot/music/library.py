from __future__ import annotations

"""已准备歌曲的本地索引与发布工具。

约束：
* ``完整音乐`` 是 QQ 唱歌的唯一发送目录，按文件名匹配歌名并发送整首；
* ``完整音乐片段`` 只供 WebUI 分段管理与试听，不参与 QQ 发送；
* 片段导出在临时目录完成，全部成功后才原子发布，避免半成品被机器人读到。
"""

import json
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from ..runtime.paths import COMPLETE_MUSIC_ROOT, DELIVERY_MUSIC_ROOT


AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".ogg", ".m4a", ".aac", ".opus"}
MANIFEST_NAME = "manifest.json"
NON_SONG_ARTIFACT_NAMES = {"execute", "function", "tool", "assistant", "none", "null", "unknown"}
# Windows 子进程偶发返回 STATUS_DLL_INIT_FAILED；重试一次通常可恢复，避免整首歌因单段失败。
FFMPEG_RETRYABLE_EXIT_CODES = {0xC0000142}


@dataclass(frozen=True)
class DeliverySongSegment:
    index: int
    path: Path
    start_seconds: float = 0.0
    end_seconds: float = 0.0
    label: str = ""

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


@dataclass(frozen=True)
class DeliverySong:
    title: str
    directory: Path
    segments: tuple[DeliverySongSegment, ...]


def safe_song_title(value: str) -> str:
    """将用户输入限制为单个目录名，杜绝路径穿越和保留设备名。"""
    title = re.sub(r"[\\/:*?\"<>|]+", "_", str(value or "").strip())
    title = re.sub(r"\s+", " ", title).strip(" ._")
    if not title or title.casefold() in {"con", "prn", "aux", "nul"}:
        raise ValueError("歌曲名称不能为空或为 Windows 保留名称")
    return title[:80]


def _normalise_title(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


_SONG_CUE_WORDS = (
    "给我唱", "帮我唱", "为我唱", "唱一首", "唱首", "唱歌", "唱一下", "唱一段",
    "来一首", "来首", "再来一首", "再来首", "挑一首", "随便一首", "任意一首",
    "歌曲", "歌", "唱", "现在唱", "行了吧", "可以吗", "能不能", "你会的", "你适合唱",
    "你可以唱", "这个", "那你", "你挑",
)


def _song_query(text: str) -> str:
    """去除 QQ @、唱歌套话和段落描述，保留用户真正说的歌名。"""
    value = re.sub(r"@[\w\u4e00-\u9fff-]+", "", str(text or ""))
    value = re.sub(r"第\s*[0-9一二三四五六七八九十百]+\s*[首段]", "", value)
    value = re.sub(r"(?:开头|前半段|中间|高潮|后半段|结尾|最后一段)", "", value)
    for word in sorted(_SONG_CUE_WORDS, key=len, reverse=True):
        value = value.replace(word, "")
    return _normalise_title(value)


def _song_aliases(song: DeliverySong) -> tuple[str, ...]:
    values = [song.title, song.directory.name]
    # 兼容“英文名（中文名）”这类文件夹，用户通常只说括号里的中文名。
    values.extend(re.findall(r"[（(]([^）)]{2,80})[）)]", song.title))
    return tuple(dict.fromkeys(alias for alias in (_normalise_title(item) for item in values) if alias))


def _song_match_score(query: str, song: DeliverySong) -> float:
    if not query:
        return 0.0
    best = 0.0
    for alias in _song_aliases(song):
        if alias in query or query in alias:
            best = max(best, 1.0)
            continue
        if len(query) >= 3 and len(alias) >= 3:
            best = max(best, SequenceMatcher(None, query, alias).ratio())
    return best


def _song_ordinal(text: str) -> int | None:
    match = re.search(r"(?:第\s*)?([0-9一二三四五六七八九十百]+)\s*首", str(text or ""))
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if raw in digits:
        return digits[raw]
    if raw == "十":
        return 10
    if raw.startswith("十"):
        return 10 + digits.get(raw[1:], 0)
    if raw.endswith("十"):
        return digits.get(raw[0], 0) * 10
    if "十" in raw:
        left, right = raw.split("十", 1)
        return digits.get(left, 0) * 10 + digits.get(right, 0)
    return None


def _read_manifest(directory: Path) -> dict[str, Any]:
    path = directory / MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _segment_from_payload(directory: Path, raw: Any, fallback_index: int) -> DeliverySongSegment | None:
    if not isinstance(raw, dict):
        return None
    filename = Path(str(raw.get("file") or "")).name
    path = (directory / filename).resolve()
    try:
        path.relative_to(directory.resolve())
    except ValueError:
        return None
    if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
        return None
    try:
        index = max(1, int(raw.get("index") or fallback_index))
        start = float(raw.get("start_seconds") or 0.0)
        end = float(raw.get("end_seconds") or 0.0)
    except (TypeError, ValueError):
        index, start, end = fallback_index, 0.0, 0.0
    return DeliverySongSegment(index, path, start, end, str(raw.get("label") or ""))


def _song_from_directory(directory: Path) -> DeliverySong | None:
    if not directory.is_dir() or directory.name.startswith("."):
        return None
    manifest = _read_manifest(directory)
    # 旧版模型工具调用曾把动作名误当成歌曲名导出，不能向用户展示或发送。
    if directory.name.strip().casefold() in NON_SONG_ARTIFACT_NAMES:
        return None
    # 片段库的文件夹名就是用户在 WebUI 中确认的歌曲名；manifest 里的 title
    # 可能来自旧版本上传路径，不能让本机绝对路径污染歌名或模型可见清单。
    title = directory.name.strip() or str(manifest.get("title") or directory.name).strip()
    segments = [
        segment
        for index, raw in enumerate(manifest.get("segments") or [], start=1)
        if (segment := _segment_from_payload(directory, raw, index)) is not None
    ]
    # 兼容用户手动放入的片段：没有 manifest 也能使用，但仍只扫描片段目录。
    if not segments:
        segments = [
            DeliverySongSegment(index, path)
            for index, path in enumerate(
                sorted(
                    (item for item in directory.iterdir() if item.is_file() and item.suffix.lower() in AUDIO_EXTENSIONS),
                    key=lambda item: item.name.casefold(),
                ),
                start=1,
            )
        ]
    if not segments:
        return None
    return DeliverySong(title, directory.resolve(), tuple(sorted(segments, key=lambda item: item.index)))


def delivery_song_catalog(root: Path = DELIVERY_MUSIC_ROOT) -> list[DeliverySong]:
    """读取 WebUI 的歌曲片段库；QQ 唱歌链路不会调用本函数。"""
    if not root.is_dir():
        return []
    return [
        song
        for directory in sorted(root.iterdir(), key=lambda item: item.name.casefold())
        if (song := _song_from_directory(directory)) is not None
    ]


def complete_song_catalog(root: Path = COMPLETE_MUSIC_ROOT) -> list[DeliverySong]:
    """读取可通过 QQ 语音发送的完整歌曲，每个文件视为一首完整歌曲。"""
    if not root.is_dir():
        return []
    songs: list[DeliverySong] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        if path.stem.strip().casefold() in NON_SONG_ARTIFACT_NAMES:
            continue
        resolved = path.resolve()
        songs.append(
            DeliverySong(
                path.stem.strip(),
                root.resolve(),
                (DeliverySongSegment(1, resolved, label="完整歌曲"),),
            )
        )
    return songs


def delivery_song_catalog_prompt(root: Path = COMPLETE_MUSIC_ROOT) -> str:
    """生成给大模型看的完整歌曲清单，不暴露本机路径。"""
    songs = complete_song_catalog(root)
    if not songs:
        return "当前完整音乐目录没有可发送歌曲，不能声称自己会唱任何歌曲。"
    lines = ["当前已学会、可以作为 QQ 语音发送整首的歌曲如下："]
    for song in songs:
        lines.append(f"- 《{song.title}》")
    lines.extend(
        (
            "选择规则：用户点名歌曲时必须选择对应歌名；无论用户是否提到“第几段/高潮”等，"
            "QQ 唱歌都发送对应完整歌曲，不发送片段；"
            "用户说“随便唱/你挑一首”时可以从清单中自然选择一首，不要反复追问。",
            "歌曲清单以本地完整音乐目录为准，不要编造未列出的歌曲。",
        )
    )
    return "\n".join(lines)


def find_complete_song(user_text: str, root: Path = COMPLETE_MUSIC_ROOT) -> DeliverySong | None:
    """按文件名及其中英文别名匹配完整歌曲。"""
    songs = complete_song_catalog(root)
    if not songs:
        return None
    query = _song_query(user_text) or _normalise_title(user_text)
    scored = sorted(
        ((_song_match_score(query, song), song) for song in songs),
        key=lambda item: item[0],
        reverse=True,
    )
    if scored and scored[0][0] >= 0.72:
        return scored[0][1]
    if _explicit_song_title(user_text):
        return None
    return songs[0] if len(songs) == 1 else None


def find_delivery_song(user_text: str, root: Path = DELIVERY_MUSIC_ROOT) -> DeliverySong | None:
    """按歌曲标题匹配；多首歌曲且用户未点名时不擅自选择。"""
    songs = delivery_song_catalog(root)
    if not songs:
        return None
    query = _normalise_title(user_text)
    matches = [song for song in songs if (name := _normalise_title(song.title)) and name in query]
    # 更长的歌名优先，避免“旅程”误匹配到名称更完整的歌曲时不稳定。
    if matches:
        return max(matches, key=lambda song: len(_normalise_title(song.title)))
    requested_title = _explicit_song_title(user_text)
    if requested_title:
        # 用户点名了一首未入库的歌，不能拿另一首歌冒充。
        return None
    return songs[0] if len(songs) == 1 else None


def select_delivery_segment(
    user_text: str,
    *,
    song_title: str = "",
    segment_index: int | None = None,
    segment_hint: str = "",
    fallback_song_title: str = "",
    previous_segment_index: int | None = None,
    root: Path = DELIVERY_MUSIC_ROOT,
) -> tuple[DeliverySong | None, DeliverySongSegment | None, str]:
    """根据用户原话和模型结构化选择，返回歌曲、片段及失败原因。"""
    songs = delivery_song_catalog(root)
    if not songs:
        return None, None, "empty"

    queries = [
        query
        for query in (
            _song_query(song_title),
            _song_query(user_text),
            _song_query(fallback_song_title),
        )
        if query
    ]
    ordinal = _song_ordinal(user_text)
    if ordinal is not None and 1 <= ordinal <= len(songs):
        song = songs[ordinal - 1]
    else:
        scored = sorted(
            ((max((_song_match_score(query, candidate) for query in queries), default=0.0), candidate) for candidate in songs),
            key=lambda item: item[0],
            reverse=True,
        )
        best_score = scored[0][0] if scored else 0.0
        if best_score >= 0.72:
            song = scored[0][1]
        elif _explicit_song_title(user_text) and queries:
            return None, None, "song_not_found"
        elif len(songs) == 1 or not queries:
            song = songs[0]
        else:
            return None, None, "song_required"

    selected_index = segment_index
    if selected_index is None:
        match = re.search(r"第\s*(\d{1,2})\s*段", str(user_text or ""))
        if match:
            selected_index = int(match.group(1))
    if selected_index is None:
        hint = f"{segment_hint}{user_text}"
        if previous_segment_index is not None and any(
            word in hint for word in ("接着", "继续", "下一段", "再来一段")
        ):
            selected_index = previous_segment_index + 1
        elif any(word in hint for word in ("后半", "最后", "结尾")):
            selected_index = song.segments[-1].index
        elif any(word in hint for word in ("中间", "高潮")):
            selected_index = song.segments[(len(song.segments) - 1) // 2].index
        else:
            selected_index = song.segments[0].index
    segment = next((item for item in song.segments if item.index == selected_index), None)
    if segment is None:
        return song, None, "segment_not_found"
    return song, segment, "ok"


def _explicit_song_title(text: str) -> str:
    value = str(text or "")
    quoted = re.search(r"[《〈\"“]([^》〉\"”]{1,80})[》〉\"”]", value)
    if quoted:
        return _normalise_title(quoted.group(1))
    match = re.search(r"(?:唱|来一首|来首)\s*([^，。！？!?\s]{2,40})", value)
    if not match:
        return ""
    candidate = _normalise_title(match.group(1))
    generic = {"一首歌", "首歌", "歌", "一段", "两句", "几句", "一下", "给我听", "给我唱"}
    return "" if candidate in generic else candidate


def save_complete_song(
    filename: str,
    data: bytes,
    *,
    root: Path = COMPLETE_MUSIC_ROOT,
) -> Path:
    """WebUI 导入完整歌曲；导入后会加入 QQ 整首歌曲发送索引。"""
    suffix = Path(filename).suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        raise ValueError("完整音乐仅支持 WAV、FLAC、MP3、OGG、M4A、AAC 或 OPUS")
    if not data:
        raise ValueError("完整音乐文件为空")
    root.mkdir(parents=True, exist_ok=True)
    stem = safe_song_title(Path(filename).stem)
    target = root / f"{stem}{suffix}"
    counter = 2
    while target.exists():
        target = root / f"{stem}_{counter}{suffix}"
        counter += 1
    temporary = target.with_suffix(target.suffix + ".uploading")
    temporary.write_bytes(data)
    temporary.replace(target)
    return target.resolve()


def complete_song_files(root: Path = COMPLETE_MUSIC_ROOT) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        (
            item.resolve()
            for item in root.iterdir()
            if item.is_file()
            and item.suffix.lower() in AUDIO_EXTENSIONS
            and item.stem.strip().casefold() not in NON_SONG_ARTIFACT_NAMES
        ),
        key=lambda item: item.name.casefold(),
    )


def export_delivery_segments(
    source: Path,
    title: str,
    *,
    target_seconds: float = 30.0,
    replace_existing: bool = False,
    complete_root: Path = COMPLETE_MUSIC_ROOT,
    delivery_root: Path = DELIVERY_MUSIC_ROOT,
) -> DeliverySong:
    """按乐理边界分段并发布到唯一可发送目录。

    这是用户主动点击 WebUI 后才执行的 CPU/磁盘任务；不会在 QQ 消息链路中触发。
    """
    source = source.expanduser().resolve()
    try:
        source.relative_to(complete_root.resolve())
    except ValueError as exc:
        raise ValueError("只能从 data/music/完整音乐 导出歌曲片段") from exc
    if not source.is_file() or source.suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValueError("请选择完整音乐目录中的有效音频")
    song_title = safe_song_title(title)
    delivery_root.mkdir(parents=True, exist_ok=True)
    destination = (delivery_root / song_title).resolve()
    try:
        destination.relative_to(delivery_root.resolve())
    except ValueError as exc:
        raise ValueError("歌曲片段输出目录无效") from exc
    if destination.exists() and not replace_existing:
        raise ValueError(f"可发送歌曲“{song_title}”已存在；为避免覆盖，请先在目录中备份或删除旧片段")
    target_seconds = min(45.0, max(20.0, float(target_seconds or 30.0)))

    # 延迟导入，平时运行 QQ 机器人不会加载 librosa/numpy，也不增加内存占用。
    from tools.voice.analyze_song_structure import plan_delivery_segments
    import imageio_ffmpeg

    plan = plan_delivery_segments(source, target_seconds=target_seconds)
    sections = list(plan.get("segments") or [])
    if not sections:
        raise ValueError("没有得到可用的歌曲分段")
    temporary_parent = Path(tempfile.mkdtemp(prefix="atri-song-export-", dir=delivery_root))
    temporary_song = temporary_parent / song_title
    temporary_song.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    try:
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        manifest_segments: list[dict[str, Any]] = []
        for index, section in enumerate(sections, start=1):
            start = float(section["start_seconds"])
            end = float(section["end_seconds"])
            duration = max(0.1, end - start)
            filename = f"{index:02d}.wav"
            output = temporary_song / filename
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
                "-i", str(source), "-vn", "-threads", "1",
                "-c:a", "pcm_s16le", str(output),
            ]
            for attempt in range(3):
                output.unlink(missing_ok=True)
                completed = subprocess.run(command, check=False, timeout=180)
                if completed.returncode == 0:
                    break
                if completed.returncode not in FFMPEG_RETRYABLE_EXIT_CODES or attempt >= 2:
                    raise subprocess.CalledProcessError(completed.returncode, command)
                time.sleep(0.8 * (attempt + 1))
            if not output.is_file() or output.stat().st_size < 1024:
                raise RuntimeError(f"第 {index} 段导出结果无效")
            manifest_segments.append(
                {
                    "index": index,
                    "file": filename,
                    "start_seconds": round(start, 3),
                    "end_seconds": round(end, 3),
                    "duration_seconds": round(duration, 3),
                    "label": str(section.get("label") or f"第 {index} 段"),
                }
            )
        manifest = {
            "version": 1,
            "title": song_title,
            "source_name": source.name,
            "target_seconds": target_seconds,
            "method": str(plan.get("method") or "beat+bar+novelty"),
            "segments": manifest_segments,
        }
        if destination.exists():
            if not replace_existing:
                raise ValueError(f"可发送歌曲“{song_title}”已存在；请启用覆盖后重试")

            # Windows 下目录可能被浏览器试听控件或杀毒软件短暂占用，不能整体 replace。
            # 改为在原目录内发布：旧文件即使被占用也保留，新文件使用唯一名称，最后只替换 manifest。
            destination.mkdir(parents=True, exist_ok=True)
            published_segments: list[dict[str, Any]] = []
            for segment in manifest_segments:
                source_file = temporary_song / str(segment["file"])
                filename = str(segment["file"])
                target_file = destination / filename
                try:
                    shutil.copy2(source_file, target_file)
                except PermissionError:
                    target_file = destination / f"{Path(filename).stem}-{uuid.uuid4().hex[:8]}{Path(filename).suffix}"
                    shutil.copy2(source_file, target_file)
                published_segment = dict(segment)
                published_segment["file"] = target_file.name
                published_segments.append(published_segment)
            manifest["segments"] = published_segments
            manifest_temp = destination / f".{MANIFEST_NAME}.{uuid.uuid4().hex}.tmp"
            manifest_temp.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            manifest_temp.replace(destination / MANIFEST_NAME)
        else:
            # 新歌曲仍使用临时目录完成后原子发布。
            (temporary_song / MANIFEST_NAME).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary_song.replace(destination)
    finally:
        shutil.rmtree(temporary_parent, ignore_errors=True)
    song = _song_from_directory(destination)
    if song is None:
        raise RuntimeError("歌曲片段发布后无法建立索引")
    return song
