from __future__ import annotations

"""预制歌曲的自然语言会话控制器。

聊天模型只负责补充理解少见表达；是否发送歌曲、发送哪一首完整歌曲，统一由
本模块裁决。这样私聊和群聊不会因模型回复、工具调用或提示词差异走出两套行为。
"""

import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from ..runtime.paths import COMPLETE_MUSIC_ROOT
from .library import DeliverySong, DeliverySongSegment, complete_song_catalog


SINGING_SESSION_TTL_SECONDS = 30 * 60

_LIST_PATTERNS = (
    "会唱什么", "会唱哪些", "会哪些歌", "会什么歌", "有什么歌", "歌曲列表",
    "歌单", "唱过什么", "学会了什么歌",
)
_STOP_PATTERNS = ("别唱了", "不要唱了", "不唱了", "停止唱歌", "停下别唱")
_SWITCH_PATTERNS = (
    "换一首", "换首", "换个歌", "换一首歌", "换首歌", "换一个", "另一首",
    "另外一首", "下一首", "再来一首", "再来首", "唱别的", "来首别的",
    "别再唱这首", "不要这首", "这首不行", "换成", "改唱",
)
_CONTINUE_PATTERNS = (
    "接着唱", "继续唱", "往下唱", "下一段", "接着来", "再来一段", "后面呢",
    "接下来呢", "然后呢",
)
_REPEAT_PATTERNS = ("再唱一遍", "重唱", "再来一次", "再唱一次", "这段再来")
_RANDOM_PATTERNS = ("随便", "你挑", "你选", "都行", "任意", "来一个", "来一首")
_SING_REQUEST_PATTERNS = (
    re.compile(r"(?:给我|为我|帮我|请|可以|能不能|能|想听你|我要听你)?.{0,3}唱"),
    re.compile(r"(?:来|整|放)(?:一首|首|一段|段)(?:歌)?"),
    re.compile(r"(?:我想听|我要听|想听)(?:一首|首|一下|你唱)"),
)
_CHINESE_NUMBERS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


@dataclass
class SingingSession:
    updated_at: float
    song_title: str = ""
    segment_index: int | None = None
    awaiting_selection: bool = False


@dataclass(frozen=True)
class SingingDecision:
    handled: bool
    reason: str = "not_singing"
    song: DeliverySong | None = None
    segment: DeliverySongSegment | None = None
    reply_text: str = ""


class SingingConversationController:
    """把自然语言点歌转换成一个确定的完整歌曲发送决策。"""

    def __init__(
        self,
        *,
        root: Path = COMPLETE_MUSIC_ROOT,
        ttl_seconds: float = SINGING_SESSION_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.root = root
        self.ttl_seconds = max(60.0, float(ttl_seconds))
        self.clock = clock
        self._sessions: dict[str, SingingSession] = {}

    def resolve(
        self,
        context_id: str,
        user_text: str,
        *,
        model_song_title: str = "",
        model_segment_index: int | None = None,
        model_segment_hint: str = "",
        force: bool = False,
    ) -> SingingDecision:
        """解析一轮点歌。

        ``force`` 只用于模型已明确调用 singing 工具的少见表达；常见自然语言在
        模型调用前就能处理。状态键应包含群号和用户号，避免群友互相串歌。
        """

        text = _clean_message(user_text)
        compact = _compact(text)
        session = self._active_session(context_id)
        songs = complete_song_catalog(self.root)

        if any(pattern in compact for pattern in _STOP_PATTERNS):
            self._sessions.pop(context_id, None)
            return SingingDecision(True, "stopped", reply_text="好，不唱了。")

        if any(pattern in compact for pattern in _LIST_PATTERNS):
            if not songs:
                return SingingDecision(True, "empty", reply_text="我还没有学会可以发送的歌哦。")
            self._sessions[context_id] = SingingSession(
                self.clock(),
                song_title=session.song_title if session else "",
                segment_index=session.segment_index if session else None,
                awaiting_selection=True,
            )
            return SingingDecision(True, "catalog", reply_text=_catalog_reply(songs))

        switch_requested = any(pattern in compact for pattern in _SWITCH_PATTERNS)
        continue_requested = any(pattern in compact for pattern in _CONTINUE_PATTERNS)
        repeat_requested = any(pattern in compact for pattern in _REPEAT_PATTERNS)
        segment_requested = _segment_index_from_text(text) is not None or any(
            word in compact for word in ("开头", "前面", "高潮", "中间", "后半", "结尾", "最后")
        )
        explicit_request = any(pattern.search(compact) for pattern in _SING_REQUEST_PATTERNS)
        awaiting_answer = bool(
            session
            and session.awaiting_selection
            and (
                _ordinal_from_text(text) is not None
                or any(word in compact for word in _RANDOM_PATTERNS)
                or bool(_match_song(text, songs))
            )
        )
        contextual_followup = bool(
            session and (switch_requested or continue_requested or repeat_requested or segment_requested)
        )

        if not (force or explicit_request or awaiting_answer or contextual_followup):
            return SingingDecision(False)
        if not songs:
            return SingingDecision(True, "empty", reply_text="这首歌我还没学会哦。")

        named_request = _requested_title_fragment(text)
        named_song = (
            _match_song(named_request, songs)
            if named_request and not _is_generic_song_fragment(named_request)
            else None
        )
        selected_song = named_song or _match_song(text, songs)
        if selected_song is None and model_song_title:
            selected_song = _match_song(model_song_title, songs)

        ordinal = _ordinal_from_text(text)
        if selected_song is None and ordinal is not None:
            if 1 <= ordinal <= len(songs):
                selected_song = songs[ordinal - 1]
            else:
                return SingingDecision(
                    True,
                    "song_index_not_found",
                    reply_text=f"我现在一共会唱 {len(songs)} 首，选一个现有的序号吧。",
                )

        if switch_requested:
            # “换一首”本身不能参与模糊歌名匹配，否则容易再次命中当前歌曲。
            # 只有用户确实说出新歌名时才采用点名结果，否则严格轮换到另一首。
            selected_song = named_song or _next_song(
                songs,
                session.song_title if session else "",
            )
            if selected_song is None:
                return SingingDecision(True, "no_alternative", reply_text="我目前只会这一首，还没有别的歌可以换哦。")

        if (
            selected_song is None
            and named_request
            and not (switch_requested or continue_requested or repeat_requested or segment_requested)
            and not _is_generic_song_fragment(named_request)
        ):
            return SingingDecision(True, "song_not_found", reply_text="这首歌我还没学会哦。")

        if selected_song is None and continue_requested and session and session.song_title:
            selected_song = _song_by_title(session.song_title, songs)
        if selected_song is None and repeat_requested and session and session.song_title:
            selected_song = _song_by_title(session.song_title, songs)
        if selected_song is None and segment_requested and session and session.song_title:
            selected_song = _song_by_title(session.song_title, songs)
        if selected_song is None and session and session.song_title and not switch_requested:
            selected_song = _song_by_title(session.song_title, songs)
        if selected_song is None:
            # “随便唱/你挑/来一首”直接选择，不再让用户重复点歌。
            selected_song = _next_song(songs, session.song_title if session else "") or songs[0]

        # 完整音乐目录中的每个文件只建立一个发送项。段号、高潮和继续唱等表达
        # 只用于确定仍在点歌语境中，绝不能把 QQ 发送重新导向片段库。
        segment = selected_song.segments[0]
        self._sessions[context_id] = SingingSession(
            self.clock(), selected_song.title, segment.index, False
        )
        return SingingDecision(True, "play", selected_song, segment)

    def _active_session(self, context_id: str) -> SingingSession | None:
        session = self._sessions.get(context_id)
        if session and self.clock() - session.updated_at <= self.ttl_seconds:
            return session
        if session:
            self._sessions.pop(context_id, None)
        return None


def _clean_message(text: str) -> str:
    value = re.sub(r"@(?:ATRI|群友|\d+)\s*", "", str(text or ""), flags=re.IGNORECASE)
    value = re.sub(r"\[用户戳了戳[^\]]*\]", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _compact(text: str) -> str:
    return re.sub(r"[\s，。！？!?、~～…]+", "", str(text or "")).casefold()


def _normalise(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(text or "").casefold())


def _song_aliases(song: DeliverySong) -> tuple[str, ...]:
    values = [song.title, song.directory.name]
    values.extend(re.findall(r"[（(]([^）)]{2,80})[）)]", song.title))
    return tuple(dict.fromkeys(value for raw in values if (value := _normalise(raw))))


def _match_song(text: str, songs: list[DeliverySong]) -> DeliverySong | None:
    query = _normalise(text)
    if not query:
        return None
    scored: list[tuple[float, int, DeliverySong]] = []
    for song in songs:
        best = 0.0
        longest = 0
        for alias in _song_aliases(song):
            longest = max(longest, len(alias))
            if alias in query:
                best = 1.0
            elif len(alias) >= 3:
                # 从整句里截取相近长度窗口，兼容“秘光之旅/秘光寻旅”一字之差。
                windows = (
                    query[index : index + len(alias)]
                    for index in range(max(1, len(query) - len(alias) + 1))
                )
                best = max(best, max((SequenceMatcher(None, window, alias).ratio() for window in windows), default=0.0))
        scored.append((best, longest, song))
    score, _, selected = max(scored, key=lambda item: (item[0], item[1]))
    return selected if score >= 0.72 else None


def _song_by_title(title: str, songs: list[DeliverySong]) -> DeliverySong | None:
    normalised = _normalise(title)
    return next((song for song in songs if _normalise(song.title) == normalised), None)


def _next_song(songs: list[DeliverySong], current_title: str) -> DeliverySong | None:
    if not songs:
        return None
    current = _song_by_title(current_title, songs) if current_title else None
    if current is None:
        return songs[0]
    if len(songs) == 1:
        return None
    index = songs.index(current)
    return songs[(index + 1) % len(songs)]


def _ordinal_from_text(text: str) -> int | None:
    match = re.search(r"(?:第\s*)?([0-9一二两三四五六七八九十]+)\s*首", str(text or ""))
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    return _CHINESE_NUMBERS.get(raw)


def _segment_index_from_text(text: str) -> int | None:
    match = re.search(r"第\s*([0-9一二两三四五六七八九十]+)\s*段", str(text or ""))
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    return _CHINESE_NUMBERS.get(raw)


def _requested_title_fragment(text: str) -> str:
    quoted = re.search(r"[《〈\"“]([^》〉\"”]{1,80})[》〉\"”]", str(text or ""))
    if quoted:
        return quoted.group(1).strip()
    match = re.search(
        r"(?:唱|听|来首|来一首|放首|放一首|换成|改唱|换首|换一首)\s*([^，。！？!?]{2,50})",
        str(text or ""),
    )
    return match.group(1).strip() if match else ""


def _is_generic_song_fragment(fragment: str) -> bool:
    value = _compact(fragment)
    generic_words = (
        "歌", "一首歌", "首歌", "一首", "一段", "几句", "一下", "给我听", "你会的",
        "随便一首", "随便", "别的", "另一首", "第二首", "第三首", "高潮", "高潮段",
        "这首", "这个", "它", "刚才那个", "上一首",
    )
    return value in generic_words or any(value.startswith(word) for word in ("一首", "一段", "几句"))


def _catalog_reply(songs: list[DeliverySong]) -> str:
    names = "、".join(f"《{song.title}》" for song in songs)
    return f"我现在会唱这些：{names}。你直接说歌名、序号，或者让我随便挑一首都可以。"
