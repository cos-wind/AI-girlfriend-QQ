"""固定点歌：列出本地歌曲，确认后作为 QQ 语音发送。"""

from atri_bot.music.library import Song, save_song, song_catalog
from atri_bot.music.session import SingingConversationController, SingingDecision

__all__ = ["Song", "save_song", "song_catalog", "SingingConversationController", "SingingDecision"]
