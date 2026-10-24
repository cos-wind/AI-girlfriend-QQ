"""账号不一致诊断：NapCat 登录号 ≠ BOT_QQ 时必须能在日志/状态里看出来。

历史事故：NapCat 登录 900000002、项目 BOT_QQ=900001003，机器人静默丢弃了
所有消息——用户只看到"发消息完全没反应"，日志里什么都没有。
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from atri_qq_bot.onebot.server_parts import server_connection
from atri_qq_bot.runtime import control


def _stub(action_results: dict[str, object]):
    class Stub:
        async def call_action_and_wait(self, websocket, action, params, timeout):
            value = action_results.get(action)
            if isinstance(value, Exception):
                raise value
            return value

    return Stub()


def test_napcat_login_uin_reads_get_login_info() -> None:
    stub = _stub({"get_login_info": {"status": "ok", "retcode": 0, "data": {"user_id": 900000002}}})

    uin = asyncio.run(
        server_connection.OneBotConnectionMixin._napcat_login_uin(stub, object())
    )

    assert uin == 900000002


def test_napcat_login_uin_is_none_when_action_fails() -> None:
    stub = _stub({"get_login_info": RuntimeError("boom")})

    assert (
        asyncio.run(
            server_connection.OneBotConnectionMixin._napcat_login_uin(stub, object())
        )
        is None
    )


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_account_mismatch_warning_names_both_accounts_and_rate_limits() -> None:
    logger = logging.getLogger("atri.onebot")
    capture = _Capture()
    logger.addHandler(capture)
    try:
        stub = SimpleNamespace(
            config=SimpleNamespace(bot_qq=900001003),
            _account_mismatch_notice_at=0.0,
        )
        server_connection.OneBotConnectionMixin._warn_account_mismatch(stub, 900000002)
        # 第二次调用应被限频吞掉，避免刷屏。
        server_connection.OneBotConnectionMixin._warn_account_mismatch(stub, 900000002)
    finally:
        logger.removeHandler(capture)

    assert len(capture.messages) == 1
    message = capture.messages[0]
    assert "900000002" in message and "900001003" in message
    assert ".env" in message


def test_foreign_account_event_warning_is_rate_limited() -> None:
    logger = logging.getLogger("atri.onebot")
    capture = _Capture()
    logger.addHandler(capture)
    try:
        stub = SimpleNamespace(
            config=SimpleNamespace(bot_qq=900001003),
            _foreign_account_event_notice_at=0.0,
        )
        server_connection.OneBotConnectionMixin._warn_foreign_account_event(stub, 900000002)
        server_connection.OneBotConnectionMixin._warn_foreign_account_event(stub, 900000002)
    finally:
        logger.removeHandler(capture)

    assert len(capture.messages) == 1
    assert "900000002" in capture.messages[0]


def test_probe_result_records_peer_uin(tmp_path, monkeypatch) -> None:
    state_file = tmp_path / "napcat-state.json"
    monkeypatch.setattr(control, "NAPCAT_STATE_FILE", state_file)

    control.publish_onebot_probe_result(
        True,
        detail="QQ 登录与消息服务正常",
        self_id=900001003,
        peer_uin=900000002,
    )

    payload = control._read_napcat_state_file()
    assert payload["peer_uin"] == 900000002


def test_runtime_status_flags_account_mismatch(tmp_path, monkeypatch) -> None:
    state_file = tmp_path / "napcat-state.json"
    monkeypatch.setattr(control, "NAPCAT_STATE_FILE", state_file)
    control.publish_onebot_probe_result(
        True,
        detail="QQ 登录与消息服务正常",
        self_id=900001003,
        peer_uin=900000002,
    )
    monkeypatch.setattr(control, "tcp_rows", lambda: [])
    # 状态文件只在"TCP 已建立"时才被当成有效；这里直接放开这一步。
    monkeypatch.setattr(control, "_has_established_port", lambda rows, port: True)
    monkeypatch.setattr(
        control, "napcat_webui_access", lambda: {"configured": False, "reachable": False}
    )

    status = control.runtime_status(
        SimpleNamespace(
            bot_qq=900001003,
            host="127.0.0.1",
            port=8765,
            webui_host="127.0.0.1",
            webui_port=8787,
            toolbox_vision_enabled=False,
            toolbox_vision_model="",
            toolbox_vision_base_url="",
            openai_base_url="http://127.0.0.1:11434/v1",
            openai_model="qwen3:4b-instruct",
            reply_mode="smart",
        )
    )

    assert status["napcat_peer_uin"] == 900000002
    assert status["napcat_account_mismatch"] is True
