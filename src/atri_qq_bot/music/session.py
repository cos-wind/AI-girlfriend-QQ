"""固定点歌：列出成品文件，用户选定后发送整首。"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..runtime.paths import MUSIC_ROOT
from .library import Song, song_catalog


SINGING_SESSION_TTL_SECONDS = 300
_CATALOG = re.compile(
    r"(?:请|给我|为我|帮我|你|能不能|可以|能|随便|想听你|我想听你)*"
    r"(?:唱(?:歌|首歌|一首歌|两句)|来一首歌|点歌|歌单|歌曲列表|都会唱什么歌|会唱什么歌)"
    r"(?:吧|呀|吗|嘛|给我听)*"
)
_NAMED = re.compile(
    r"(?P<prefix>请|给我|为我|帮我|你能不能|你可以|能不能|可以)?"
    r"唱(?P<title>[^，。！？!?\n]{1,100}?)(?:给我听|吧|呀|吗)*"
)
_CONFIRM = {"确认", "确定", "是", "是的", "对", "就这首", "是的就这首"}
_CANCEL = {"取消", "算了", "不唱了", "别唱了", "不要唱了"}


@dataclass
class SingingSession:
    updated_at: float
    songs: list[Song]
    candidate: Song | None = None


@dataclass(frozen=True)
class SingingDecision:
    handled: bool
    reason: str = "not_singing"
    song: Song | None = None
    reply_text: str = ""


class SingingConversationController:
    def __init__(
        self,
        *,
        root: Path = MUSIC_ROOT,
        ttl_seconds: float = SINGING_SESSION_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.root = root
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._sessions: dict[str, SingingSession] = {}

    def resolve(self, context_id: str, user_text: str) -> SingingDecision:
        text = re.sub(r"@[\w\u4e00-\u9fff-]+\s*", "", user_text).strip()
        text = re.sub(r"^(?:亚托莉|ATRI)[，,\s]*", "", text, flags=re.IGNORECASE)
        text = text.strip(" ，,。！？!?~～")
        session = self._sessions.pop(context_id, None)
        if session and self.clock() - session.updated_at > self.ttl_seconds:
            session = None
        if session and text in _CANCEL:
            return SingingDecision(True, "stopped", reply_text="好，不唱了。")
        if _CATALOG.fullmatch(text):
            return self._catalog(context_id)

        named = _NAMED.fullmatch(text)
        title = named.group("title") if named else text
        title = re.sub(r"^(?:就|我选|选)", "", title).removesuffix("吧")
        if session:
            song = _find_song(title, session.songs)
            number = re.fullmatch(r"第?([0-9一二三四五六七八九十]+)(?:首)?", title)
            if number:
                raw = number.group(1)
                index = int(raw) if raw.isdigit() else dict(zip("一二三四五六七八九十", range(1, 11))).get(raw, 0)
                song = session.songs[index - 1] if 1 <= index <= len(session.songs) else None
            if text.replace("，", "") in _CONFIRM:
                song = session.candidate
            if song:
                if song.path.is_file():
                    return SingingDecision(True, "play", song)
                return self._catalog(context_id)
            if number or text in _CONFIRM:
                return self._catalog(context_id)

        if named:
            songs = song_catalog(self.root)
            candidate = _find_song(title, songs)
            if candidate or named.group("prefix") or title.startswith("《"):
                return self._catalog(context_id, songs=songs, candidate=candidate)
        return SingingDecision(False)

    def _catalog(
        self,
        context_id: str,
        *,
        songs: list[Song] | None = None,
        candidate: Song | None = None,
    ) -> SingingDecision:
        songs = song_catalog(self.root) if songs is None else songs
        if not songs:
            return SingingDecision(True, "empty", reply_text="歌单暂时是空的，还没有可以发送的成品歌曲。")
        self._sessions[context_id] = SingingSession(self.clock(), songs, candidate)
        lines = ["我现在的歌单：", *(f"{i}. 《{song.title}》" for i, song in enumerate(songs, 1))]
        lines.append(
            f"你点的是《{candidate.title}》，回复“确认”发送。"
            if candidate else "回复歌名或序号，我会用语音消息发送整首歌。"
        )
        return SingingDecision(True, "catalog", reply_text="\n".join(lines))


def _find_song(text: str, songs: list[Song]) -> Song | None:
    title = text.strip('《》“”" ').casefold()
    matches = [song for song in songs if title in (
        song.title.casefold(), *(alias.casefold() for alias in re.findall(r"[（(]([^）)]+)[）)]", song.title))
    )]
    return matches[0] if len(matches) == 1 else None
