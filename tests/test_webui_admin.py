import json
import threading
from pathlib import Path

from atri_qq_bot.config import BotConfig
from atri_qq_bot.runtime.control import runtime_status
from atri_webui.memory_admin import MemoryAdmin
from atri_webui.sticker_admin import resolve_under, sticker_file_payload
from atri_webui.upload_parser import (
    multipart_file,
    multipart_text,
    parse_multipart_form,
)


def test_memory_admin_summarizes_and_reads_details(tmp_path: Path) -> None:
    memory_path = tmp_path / "users.json"
    backup_dir = tmp_path / "backups"
    memory_path.write_text(
        json.dumps(
            {
                "version": 2,
                "conversations": {
                    "private:10001": {
                        "target": {"user_id": 10001},
                        "message_count": 2,
                        "last_user_at": 1000,
                        "affection_score": 70,
                        "structured_memory": {
                            "l1": [
                                {
                                    "category": "interest",
                                    "key": "likes-tests",
                                    "value": "喜欢稳定的回归测试",
                                }
                            ],
                            "l2": [],
                            "candidates": [],
                        },
                        "history": [{"role": "user", "nickname": "主人", "text": "记得测试一下"}],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    admin = MemoryAdmin(memory_path, backup_dir)

    summary = admin.summary()
    detail = admin.detail("id=private%3A10001")

    assert summary["path"] == str(memory_path)
    assert summary["conversations"] == 1
    assert summary["items"][0]["kind"] == "private"
    assert summary["items"][0]["memory_counts"]["total"] == 1
    assert "喜欢稳定的回归测试" in summary["items"][0]["searchable"]
    assert detail["ok"] is True
    assert detail["content"]["message_count"] == 2


def test_memory_admin_backs_up_before_atomic_save(tmp_path: Path) -> None:
    memory_path = tmp_path / "users.json"
    backup_dir = tmp_path / "backups"
    original = {
        "version": 2,
        "conversations": {
            "private:10001": {
                "message_count": 1,
                "history": [{"role": "user", "text": "old"}],
            }
        },
    }
    memory_path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    admin = MemoryAdmin(memory_path, backup_dir)

    backup = admin.save_conversation(
        "private:10001",
        {"message_count": 2, "history": [{"role": "user", "text": "new"}]},
    )

    saved = json.loads(memory_path.read_text(encoding="utf-8"))
    backed_up = json.loads(backup.read_text(encoding="utf-8"))
    assert saved["conversations"]["private:10001"]["message_count"] == 2
    assert backed_up == original
    assert not list(tmp_path.glob("*.tmp"))


def test_memory_admin_serializes_concurrent_writes(tmp_path: Path) -> None:
    memory_path = tmp_path / "users.json"
    backup_dir = tmp_path / "backups"
    memory_path.write_text(
        json.dumps(
            {
                "version": 2,
                "conversations": {
                    "private:10001": {"message_count": 1},
                    "private:10002": {"message_count": 1},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    admin = MemoryAdmin(memory_path, backup_dir)
    errors: list[Exception] = []

    def save(conversation_id: str, count: int) -> None:
        try:
            admin.save_conversation(conversation_id, {"message_count": count})
        except Exception as exc:  # pragma: no cover - failures are asserted below
            errors.append(exc)

    threads = [
        threading.Thread(target=save, args=("private:10001", 2)),
        threading.Thread(target=save, args=("private:10002", 3)),
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    saved = json.loads(memory_path.read_text(encoding="utf-8"))
    assert errors == []
    assert saved["conversations"]["private:10001"]["message_count"] == 2
    assert saved["conversations"]["private:10002"]["message_count"] == 3
    assert len(list(backup_dir.glob("users.webui-edit-*.json"))) == 2
    assert not list(tmp_path.glob("*.tmp"))


def test_memory_admin_rejects_invalid_save_payload(tmp_path: Path) -> None:
    memory_path = tmp_path / "users.json"
    backup_dir = tmp_path / "backups"
    memory_path.write_text(
        json.dumps({"version": 2, "conversations": {"private:1": {}}}),
        encoding="utf-8",
    )
    admin = MemoryAdmin(memory_path, backup_dir)

    try:
        admin.save_conversation("private:1", ["not", "a", "dict"])  # type: ignore[arg-type]
    except ValueError as exc:
        assert "JSON" in str(exc)
    else:
        raise AssertionError("expected invalid memory payload to be rejected")


def test_runtime_status_keeps_webui_contract(monkeypatch) -> None:
    calls: list[int] = []

    def fake_is_port_listening(port: int) -> bool:
        calls.append(port)
        return port == 8765

    monkeypatch.setattr("atri_qq_bot.runtime.control.is_port_listening", fake_is_port_listening)
    monkeypatch.setattr("atri_qq_bot.runtime.control.has_established_port", lambda port: port == 8765)

    config = BotConfig(
        bot_qq=3380609082,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
    )

    status = runtime_status(config)

    assert status["atri"] is True
    assert status["napcat"] is True
    assert status["ollama"] is False
    assert status["onebot"] == "ws://127.0.0.1:8765/onebot"
    assert status["webui_url"] == "http://127.0.0.1:8787"
    assert calls == [8765, 11434]


def test_sticker_admin_payload_and_path_guard(tmp_path: Path, monkeypatch) -> None:
    sticker_root = tmp_path / "stickers"
    image = sticker_root / "happy" / "atri smile.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr("atri_webui.sticker_admin.STICKER_ROOT", sticker_root)

    payload = sticker_file_payload(image)

    assert payload["path"] == "happy/atri smile.png"
    assert payload["url"].endswith("happy%2Fatri%20smile.png")
    assert resolve_under(sticker_root, "happy/atri%20smile.png") == image.resolve()
    assert resolve_under(sticker_root, "../secret.png") is None


def test_multipart_upload_parser_reads_text_and_file() -> None:
    boundary = "atri-test-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="category"\r\n'
        "\r\n"
        "happy\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="smile.png"\r\n'
        "Content-Type: image/png\r\n"
        "\r\n"
    ).encode("utf-8") + b"\x89PNG\r\n\x1a\n" + f"\r\n--{boundary}--\r\n".encode("utf-8")

    form = parse_multipart_form(f"multipart/form-data; boundary={boundary}", body)
    file_part = multipart_file(form, "file")

    assert multipart_text(form, "category") == "happy"
    assert file_part is not None
    assert file_part.filename == "smile.png"
    assert file_part.data == b"\x89PNG\r\n\x1a\n"


def test_multipart_upload_parser_rejects_non_multipart_body() -> None:
    try:
        parse_multipart_form("application/json", b"{}")
    except ValueError as exc:
        assert "multipart/form-data" in str(exc)
    else:
        raise AssertionError("expected non-multipart uploads to be rejected")
