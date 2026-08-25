"""预制完整歌曲发送索引与 WebUI 片段管理库。

这里与 TTS、歌声模型彻底解耦：只管理已经人工确认过的音频文件，
供 OneBot 作为 QQ 语音消息发送。
"""

from .library import (
    AUDIO_EXTENSIONS,
    DeliverySong,
    DeliverySongSegment,
    complete_song_catalog,
    complete_song_files,
    delivery_song_catalog,
    delivery_song_catalog_prompt,
    export_delivery_segments,
    find_delivery_song,
    find_complete_song,
    select_delivery_segment,
    save_complete_song,
)
from .session import SingingConversationController, SingingDecision, SingingSession

__all__ = [
    "AUDIO_EXTENSIONS",
    "DeliverySong",
    "DeliverySongSegment",
    "complete_song_catalog",
    "complete_song_files",
    "delivery_song_catalog",
    "delivery_song_catalog_prompt",
    "export_delivery_segments",
    "find_delivery_song",
    "find_complete_song",
    "select_delivery_segment",
    "save_complete_song",
    "SingingConversationController",
    "SingingDecision",
    "SingingSession",
]
