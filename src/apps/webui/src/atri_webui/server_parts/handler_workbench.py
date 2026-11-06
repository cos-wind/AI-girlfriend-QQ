"""歌曲工作台（AI_music）的入口处理器。

工作流本身已经不在本项目里，因此这里只有两件事：只读探活与"调用对方启动脚本"。
不转发任何工程数据，也不读取对方的目录，保证两边彻底解耦。
"""

from __future__ import annotations

from .handler_support import WebUIHandlerMixin, _sync_webui_globals


class HandlerWorkbenchMixin(WebUIHandlerMixin):
    def _handle_music_workbench_status(self) -> None:
        """只读：前端、桥接、语音服务三段状态。"""

        self._send_json(music_workbench_status())

    def _handle_music_workbench_start(self) -> None:
        """调用 AI_music 自己的启动脚本；找不到脚本或 PowerShell 时给出明确原因。"""

        try:
            result = start_music_workbench()
        except FileNotFoundError as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, str(exc))
        except OSError as exc:
            return self._send_error(HTTPStatus.BAD_GATEWAY, f"工作台启动失败：{exc}")
        self._send_json(result)
