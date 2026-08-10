import asyncio
import json
import threading
from pathlib import Path

from atri_qq_bot.config import BotConfig
from atri_qq_bot.runtime.control import runtime_status
from atri_webui import config_admin
from atri_webui.memory_admin import MemoryAdmin
from atri_webui import model_profiles as model_profiles_module
from atri_webui import server as webui_server
from atri_webui.model_profiles import (
    activate_model_profile,
    local_models_payload,
    load_model_profiles,
    model_profiles_payload,
    scan_ollama_manifest_models,
    upsert_model_profile,
)
from atri_webui.page import render_index
from atri_webui.sticker_admin import resolve_under, sticker_file_payload, sticker_summary
from atri_webui import voice_admin
from atri_webui.voice_admin import resolve_voice_audio, save_reference_audio, save_test_audio
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
    assert summary["items"][0]["id"] == "person:10001"
    assert summary["items"][0]["kind"] == "person"
    assert summary["items"][0]["type"] == "人物档案"
    assert summary["items"][0]["memory_counts"]["total"] == 1
    assert "喜欢稳定的回归测试" in summary["items"][0]["searchable"]
    assert detail["ok"] is True
    assert detail["content"]["message_count"] == 2


def test_memory_detail_exposes_only_three_memory_layers(tmp_path: Path) -> None:
    memory_path = tmp_path / "users.json"
    memory_path.write_text(
        json.dumps(
            {
                "version": 2,
                "conversations": {
                    "private:10001": {
                        "target": {"user_id": 10001},
                        "structured_memory": {
                            "l1": [{"category": "habit", "key": "作息", "value": "晚上学习"}],
                            "l2": [{"category": "event", "key": "明天:考试", "value": "明天有考试"}],
                            "l3": [{"layer": "L3", "category": "session_context", "text": "当前正在讨论记忆系统", "value": "当前正在讨论记忆系统"}],
                            "candidates": [],
                        },
                        "history": [{"role": "user", "text": "这句原始历史不应混入概览"}],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    detail = MemoryAdmin(memory_path, tmp_path / "backups").detail("id=private%3A10001")

    assert [entry["value"] for entry in detail["layers"]["l1"]] == ["晚上学习"]
    assert [entry["value"] for entry in detail["layers"]["l2"]] == ["明天有考试"]
    assert [entry["text"] for entry in detail["layers"]["l3"]] == ["当前正在讨论记忆系统"]
    assert "这句原始历史不应混入概览" not in detail["natural"]


def test_memory_tabs_use_layer_names() -> None:
    html = render_index()

    assert "L1 用户特点" in html
    assert "L2 事件" in html
    assert "L3 最近聊天" in html
    assert '>习惯<' not in html


def test_memory_admin_person_summary_merges_private_and_group_member(
    tmp_path: Path,
) -> None:
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
                        "structured_memory": {
                            "l1": [
                                {
                                    "category": "profile_fact",
                                    "key": "生日",
                                    "value": "8月12日",
                                }
                            ],
                            "l2": [],
                            "candidates": [],
                        },
                    },
                    "group:20001:user:10001": {
                        "target": {"group_id": 20001, "user_id": 10001},
                        "message_count": 3,
                        "last_user_at": 1200,
                        "structured_memory": {
                            "l1": [
                                {
                                    "category": "interest",
                                    "key": "兴趣:咖啡",
                                    "value": "咖啡",
                                    "visibility": "group:20001",
                                }
                            ],
                            "l2": [],
                            "candidates": [],
                        },
                        "history": [{"role": "user", "nickname": "余弦寄长风", "text": "我喜欢喝咖啡"}],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    admin = MemoryAdmin(memory_path, backup_dir)

    summary = admin.summary()
    detail = admin.detail("id=person%3A10001")

    assert [item["id"] for item in summary["items"]] == ["person:10001"]
    assert summary["items"][0]["messages"] == 5
    assert summary["items"][0]["related_count"] == 2
    assert "余弦寄长风" in summary["items"][0]["display_name"]
    assert detail["ok"] is True
    assert detail["id"] == "person:10001"
    assert detail["storage_id"] == "private:10001"
    assert detail["group_infos"][0]["group_id"] == "20001"
    assert detail["group_infos"][0]["messages"] == 3
    values = json.dumps(detail["content"]["structured_memory"], ensure_ascii=False)
    assert "8月12日" in values
    assert "咖啡" in values


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


def test_memory_admin_normalizes_manual_structured_entries(tmp_path: Path) -> None:
    memory_path = tmp_path / "users.json"
    backup_dir = tmp_path / "backups"
    memory_path.write_text(
        json.dumps(
            {"version": 2, "conversations": {"private:10001": {"message_count": 1}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    admin = MemoryAdmin(memory_path, backup_dir)

    admin.save_conversation(
        "private:10001",
        {
            "message_count": 1,
            "structured_memory": {
                "l1": [
                    {
                        "category": "interest",
                        "key": "兴趣:咖啡",
                        "value": "咖啡",
                        "confidence": 0.8,
                    }
                ],
                "l2": [],
                "candidates": [],
            },
        },
    )

    saved = json.loads(memory_path.read_text(encoding="utf-8"))
    entry = saved["conversations"]["private:10001"]["structured_memory"]["l1"][0]
    assert entry["memory_key"] == "interest:兴趣:咖啡"
    assert entry["id"] == "l1:interest:兴趣:咖啡"
    assert entry["source"] == "webui"
    assert entry["locked"] is True


def test_memory_admin_validates_manual_affection_and_proactive_override(tmp_path: Path) -> None:
    memory_path = tmp_path / "users.json"
    backup_dir = tmp_path / "backups"
    memory_path.write_text(
        json.dumps({"version": 2, "conversations": {"private:10001": {"message_count": 1}}}),
        encoding="utf-8",
    )
    admin = MemoryAdmin(memory_path, backup_dir)

    admin.save_conversation(
        "private:10001",
        {"message_count": 1, "affection_score": 120, "proactive_override": "allow"},
    )
    saved = json.loads(memory_path.read_text(encoding="utf-8"))["conversations"]["private:10001"]

    assert saved["affection_score"] == 100
    assert saved["affection_initialized"] is True
    assert saved["last_affection_idle_decay_at"] > 0
    assert saved["proactive_override"] == "allow"


def test_memory_admin_relationship_patch_preserves_other_memory_fields(tmp_path: Path) -> None:
    memory_path = tmp_path / "users.json"
    backup_dir = tmp_path / "backups"
    original_item = {
        "target": {"message_type": "private", "user_id": 10001},
        "message_count": 18,
        "history": [{"role": "user", "text": "不要改这段历史"}],
        "structured_memory": {"l1": [], "l2": [], "candidates": []},
        "affection_score": 20,
    }
    memory_path.write_text(
        json.dumps(
            {"version": 2, "conversations": {"private:10001": original_item}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    admin = MemoryAdmin(memory_path, backup_dir)

    backup, relationship = admin.update_relationship("person:10001", 88.5, "deny")
    saved = json.loads(memory_path.read_text(encoding="utf-8"))["conversations"]["private:10001"]

    assert relationship == {
        "affection_score": 88.5,
        "group_activity_score": None,
        "proactive_override": "deny",
        "trust_tier": "probation",
    }
    assert saved["message_count"] == 18
    assert saved["history"] == original_item["history"]
    assert saved["structured_memory"] == original_item["structured_memory"]
    assert saved["affection_score"] == 88.5
    assert json.loads(backup.read_text(encoding="utf-8"))["conversations"]["private:10001"] == original_item


def test_memory_admin_updates_group_activity_without_creating_affection(tmp_path: Path) -> None:
    memory_path = tmp_path / "users.json"
    backup_dir = tmp_path / "backups"
    group_item = {
        "target": {"message_type": "group", "group_id": 1054646184},
        "message_count": 120,
        "group_activity_score": 12,
        "history": [{"role": "user", "text": "群消息"}],
    }
    memory_path.write_text(
        json.dumps(
            {"version": 2, "conversations": {"group:1054646184": group_item}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    admin = MemoryAdmin(memory_path, backup_dir)

    _, relationship = admin.update_relationship(
        "group:1054646184",
        None,
        "allow",
        76.5,
    )
    saved = json.loads(memory_path.read_text(encoding="utf-8"))["conversations"]["group:1054646184"]

    assert relationship == {
        "affection_score": None,
        "group_activity_score": 76.5,
        "proactive_override": "allow",
    }
    assert saved["group_activity_score"] == 76.5
    assert saved["last_group_activity_at"] > 0
    assert "affection_score" not in saved
    assert saved["message_count"] == 120
    assert saved["history"] == group_item["history"]


def test_memory_admin_private_edit_cleans_same_person_group_stale_values(
    tmp_path: Path,
) -> None:
    memory_path = tmp_path / "users.json"
    backup_dir = tmp_path / "backups"
    memory_path.write_text(
        json.dumps(
            {
                "version": 2,
                "conversations": {
                    "private:10001": {
                        "structured_memory": {
                            "l1": [
                                {
                                    "category": "interest",
                                    "key": "兴趣:奶茶",
                                    "value": "奶茶",
                                }
                            ],
                            "l2": [],
                            "candidates": [],
                        }
                    },
                    "group:20001:user:10001": {
                        "structured_memory": {
                            "l1": [
                                {
                                    "category": "interest",
                                    "key": "兴趣:奶茶",
                                    "value": "奶茶",
                                }
                            ],
                            "l2": [],
                            "candidates": [],
                        }
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    admin = MemoryAdmin(memory_path, backup_dir)

    admin.save_conversation(
        "private:10001",
        {
            "structured_memory": {
                "l1": [
                    {
                        "category": "interest",
                        "key": "兴趣:咖啡",
                        "value": "咖啡",
                    }
                ],
                "l2": [],
                "candidates": [],
            }
        },
    )

    saved = json.loads(memory_path.read_text(encoding="utf-8"))
    group_entries = saved["conversations"]["group:20001:user:10001"][
        "structured_memory"
    ]["l1"]
    private_entries = saved["conversations"]["private:10001"]["structured_memory"]["l1"]
    assert not group_entries
    assert private_entries[0]["value"] == "咖啡"


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


def test_local_ollama_manifest_models_are_discovered(tmp_path: Path) -> None:
    manifest = (
        tmp_path
        / "models"
        / "manifests"
        / "registry.ollama.ai"
        / "library"
        / "qwen2.5"
        / "7b"
    )
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")

    models = scan_ollama_manifest_models(tmp_path)
    payload = local_models_payload(tmp_path, include_api=False)

    assert models[0]["name"] == "qwen2.5:7b"
    assert payload["models_path"] == str(tmp_path)
    assert payload["models"][0]["name"] == "qwen2.5:7b"
    assert payload["models"][0]["runnable"] is False


def test_local_ollama_models_root_accepts_direct_manifest_layout(tmp_path: Path) -> None:
    manifest = (
        tmp_path
        / "manifests"
        / "registry.ollama.ai"
        / "library"
        / "qwen3"
        / "4b-instruct"
    )
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")
    unrelated = tmp_path / "manifests" / "voice-runtime" / ".venv" / "python.exe"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b"not a model manifest")

    models = scan_ollama_manifest_models(tmp_path)

    assert [model["name"] for model in models] == ["qwen3:4b-instruct"]


def test_model_profiles_payload_includes_provider_catalog(tmp_path: Path) -> None:
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="ollama",
        openai_base_url="http://127.0.0.1:11434/v1",
        openai_model="qwen2.5:7b",
        temperature=0.65,
        max_tokens=260,
        memory_path=tmp_path / "users.json",
    )

    payload = model_profiles_payload(config)
    provider_ids = {provider["id"] for provider in payload["provider_catalog"]}

    assert {"ollama", "deepseek", "openai", "custom"}.issubset(provider_ids)


def test_model_profiles_payload_tracks_active_profiles_by_type(
    tmp_path: Path, monkeypatch
) -> None:
    profile_path = tmp_path / "model_profiles.json"
    monkeypatch.setattr(model_profiles_module, "MODEL_PROFILE_PATH", profile_path)
    monkeypatch.setattr(model_profiles_module, "WEBUI_DIR", tmp_path)
    profile_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "chat-qwen",
                        "name": "聊天 Qwen",
                        "model_type": "chat",
                        "provider": "Ollama",
                        "base_url": "http://127.0.0.1:11434/v1",
                        "model": "qwen2.5:7b",
                        "api_key": "ollama",
                    },
                    {
                        "id": "vision-qwen",
                        "name": "视觉 Qwen",
                        "model_type": "vision",
                        "provider": "Ollama",
                        "base_url": "http://127.0.0.1:11434/v1",
                        "model": "qwen2.5vl:3b",
                        "api_key": "ollama",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="ollama",
        openai_base_url="http://127.0.0.1:11434/v1",
        openai_model="qwen2.5:7b",
        temperature=0.65,
        max_tokens=260,
        toolbox_vision_enabled=True,
        toolbox_vision_model="qwen2.5vl:3b",
        toolbox_vision_base_url="http://127.0.0.1:11434/v1",
        toolbox_vision_api_key="ollama",
        memory_path=tmp_path / "users.json",
    )

    payload = model_profiles_payload(config)

    assert payload["active_id"] == "chat-qwen"
    assert payload["active_ids"] == {"chat": "chat-qwen", "vision": "vision-qwen"}
    assert payload["current_by_type"]["chat"]["model"] == "qwen2.5:7b"
    assert payload["current_by_type"]["vision"]["model"] == "qwen2.5vl:3b"


def test_activate_vision_profile_does_not_replace_chat_model(
    tmp_path: Path, monkeypatch
) -> None:
    profile_path = tmp_path / "model_profiles.json"
    env_path = tmp_path / ".env"
    monkeypatch.setattr(model_profiles_module, "MODEL_PROFILE_PATH", profile_path)
    monkeypatch.setattr(model_profiles_module, "WEBUI_DIR", tmp_path)
    monkeypatch.setattr(config_admin, "ENV_PATH", env_path)
    profile_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "vision-qwen",
                        "name": "视觉 Qwen",
                        "model_type": "vision",
                        "provider": "Ollama",
                        "base_url": "http://127.0.0.1:11434/v1",
                        "model": "qwen2.5vl:7b",
                        "api_key": "ollama",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=chat-key",
                "OPENAI_BASE_URL=http://chat.example/v1",
                "OPENAI_MODEL=qwen2.5:7b",
                "TOOLBOX_VISION_MODEL=qwen2.5vl:3b",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    activated = activate_model_profile("vision-qwen")
    env = config_admin.read_env()

    assert activated["model_type"] == "vision"
    assert env["OPENAI_API_KEY"] == "chat-key"
    assert env["OPENAI_BASE_URL"] == "http://chat.example/v1"
    assert env["OPENAI_MODEL"] == "qwen2.5:7b"
    assert env["TOOLBOX_VISION_ENABLED"] == "true"
    assert env["TOOLBOX_VISION_API_KEY"] == "ollama"
    assert env["TOOLBOX_VISION_BASE_URL"] == "http://127.0.0.1:11434/v1"
    assert env["TOOLBOX_VISION_MODEL"] == "qwen2.5vl:7b"


def test_upsert_vision_profile_prefers_existing_vision_api_key(
    tmp_path: Path, monkeypatch
) -> None:
    profile_path = tmp_path / "model_profiles.json"
    env_path = tmp_path / ".env"
    monkeypatch.setattr(model_profiles_module, "MODEL_PROFILE_PATH", profile_path)
    monkeypatch.setattr(model_profiles_module, "WEBUI_DIR", tmp_path)
    monkeypatch.setattr(config_admin, "ENV_PATH", env_path)
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=chat-key",
                "TOOLBOX_VISION_API_KEY=vision-key",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    profile = upsert_model_profile(
        {
            "name": "视觉模型",
            "model_type": "vision",
            "provider": "Ollama",
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "qwen2.5vl:7b",
            "api_key": "",
        }
    )

    assert profile["api_key"] == "vision-key"


def test_builtin_profile_collision_is_repaired_without_losing_local_profile(
    tmp_path: Path, monkeypatch
) -> None:
    profile_path = tmp_path / "model_profiles.json"
    monkeypatch.setattr(model_profiles_module, "MODEL_PROFILE_PATH", profile_path)
    monkeypatch.setattr(model_profiles_module, "WEBUI_DIR", tmp_path)
    profile_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "deepseek-official-chat",
                        "name": "本地 Ollama deepseek-r1:8b",
                        "model_type": "chat",
                        "provider": "Ollama",
                        "base_url": "http://127.0.0.1:11434/v1",
                        "model": "deepseek-r1:8b",
                        "api_key": "ollama",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    profiles = load_model_profiles()
    ids = {profile["id"] for profile in profiles}
    models = {profile["model"] for profile in profiles}
    saved = json.loads(profile_path.read_text(encoding="utf-8"))

    assert "deepseek-official-chat" in ids
    assert "deepseek-r1:8b" in models
    assert "deepseek-v4-flash" in models
    assert any(
        profile["id"] != "deepseek-official-chat"
        and profile["model"] == "deepseek-r1:8b"
        for profile in saved["profiles"]
    )


def test_deprecated_deepseek_profile_is_migrated_without_losing_api_key(
    tmp_path: Path, monkeypatch
) -> None:
    profile_path = tmp_path / "model_profiles.json"
    monkeypatch.setattr(model_profiles_module, "MODEL_PROFILE_PATH", profile_path)
    monkeypatch.setattr(model_profiles_module, "WEBUI_DIR", tmp_path)
    profile_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "deepseek-official-chat",
                        "name": "Deepseek-chat",
                        "model_type": "chat",
                        "provider": "DeepSeek",
                        "base_url": "https://api.deepseek.com/v1",
                        "model": "deepseek-chat",
                        "api_key": "saved-key",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    profiles = load_model_profiles()

    assert profiles[0]["model"] == "deepseek-v4-flash"
    assert profiles[0]["name"] == "DeepSeek V4 Flash"
    assert profiles[0]["api_key"] == "saved-key"
    saved = json.loads(profile_path.read_text(encoding="utf-8"))
    assert saved["profiles"][0]["model"] == "deepseek-v4-flash"


def test_model_page_shows_feedback_for_local_model_actions() -> None:
    html = render_index()

    assert "id=\"localModelAction\"" in html
    assert "id=\"modelFillFeedback\"" in html
    assert "id=\"profileModelType\"" in html
    assert "loadLocalModels({manual:true})" in html
    assert ".model-card.selected" in html
    assert "markLocalModelSelected(model.name)" in html
    assert "showProfileFillFeedback" in html
    assert "active_ids" in html
    assert "current_by_type" in html
    assert "profile-columns" in html
    assert "deleteProfileByIndex" in html
    assert "beginNewModelProfileFromFill" in html
    assert "testCurrentChatModel" in html
    assert "model-workspace" in html
    assert "仅发现模型文件" in html


def test_voice_page_has_separate_policy_profile_and_preview_controls() -> None:
    html = render_index()

    assert "onclick=\"showTab(event,'voice')\"" in html
    assert 'id="voiceAsrEnabled"' in html
    assert 'id="voiceTtsEnabled"' in html
    assert '<select id="voiceProfileId"' in html
    assert 'id="voiceReferenceFile"' in html
    assert 'id="voicePreviewLanguage"' in html
    assert 'id="voicePreviewAudio"' in html
    assert "async function previewVoice()" in html
    assert "language:$(\'voicePreviewLanguage\').value" in html
    assert 'id="voiceAsrLexicon"' in html
    assert "asr_lexicon_text:$('voiceAsrLexicon').value" in html
    assert 'id="voiceTtsPronunciations"' in html
    assert "tts_pronunciation_text:$('voiceTtsPronunciations').value" in html


def test_advanced_reply_settings_include_voice_probability_control() -> None:
    html = render_index()

    assert 'id="replyVoiceProbabilityNumber"' in html
    assert '["REPLY_VOICE_PROBABILITY","语音概率（%）","voice-probability"]' in html
    assert 'if(type===\'voice-probability\') continue;' in html
    assert "async function loadReplyVoiceProbability()" in html
    assert "async function saveReplyVoiceProbability()" in html
    assert "/api/voice/behavior" in html
    assert "reply_voice_probability:probability" in html
    assert "await saveReplyVoiceProbability();" in html


def test_test_page_has_asr_and_tts_acceptance_controls() -> None:
    html = render_index()

    assert 'id="testAsrFile"' in html
    assert 'id="testAsrLanguage"' in html
    assert 'id="testAsrRecordButton"' in html
    assert 'id="testAsrStopButton"' in html
    assert 'id="testAsrOut"' in html
    assert 'id="testTtsText"' in html
    assert 'id="testTtsLanguage"' in html
    assert 'id="testTtsProfileA"' in html
    assert 'id="testTtsProfileB"' in html
    assert 'id="testTtsAudioA"' in html
    assert 'id="testTtsAudioB"' in html
    assert "/api/voice/test-asr" in html
    assert "async function startAsrRecording()" in html
    assert "function stopAsrRecording()" in html
    assert "async function testVoiceRecognition(fileOverride=null)" in html
    assert "form.append('language'" in html
    assert "async function testVoiceSynthesis()" in html
    assert "async function testVoiceComparison()" in html


def test_voice_reference_is_saved_inside_profile_directory(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "voice"
    monkeypatch.setattr(voice_admin, "VOICE_ROOT", root)
    monkeypatch.setattr(voice_admin, "VOICE_PROFILE_DIR", root / "profiles")
    voice_admin.voice_profile_store()

    profile = save_reference_audio("atri", "sample.wav", b"RIFFvoice")
    saved = Path(profile.reference_audio)

    assert saved.read_bytes() == b"RIFFvoice"
    assert saved.is_relative_to(root)
    assert resolve_voice_audio(str(saved)) == saved.resolve()


def test_voice_test_audio_is_saved_in_cache_with_safe_generated_name(
    tmp_path: Path, monkeypatch
) -> None:
    cache = tmp_path / "cache"
    monkeypatch.setattr(voice_admin, "VOICE_CACHE_DIR", cache)

    saved = save_test_audio("../../user recording.wav", b"RIFFvoice")

    assert saved.parent == cache.resolve()
    assert saved.name.startswith("asr-test-")
    assert saved.suffix == ".wav"
    assert saved.read_bytes() == b"RIFFvoice"


def test_webui_test_chat_reports_when_fallback_is_used(
    tmp_path: Path, monkeypatch
) -> None:
    class FailingEngine:
        def __init__(self, config) -> None:
            self.config = config

        async def _reply_with_guarded_api(self, *args, **kwargs) -> str:
            raise RuntimeError("backend unavailable")

        def _fallback_reply(self, conversation_id: str, text: str) -> str:
            return "fallback reply"

    monkeypatch.setattr(webui_server, "AtriReplyEngine", FailingEngine)
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=100,
        memory_path=tmp_path / "users.json",
    )

    result = asyncio.run(webui_server.test_chat(config, "你好"))

    assert result["used_ai"] is False
    assert result["reply"] == "fallback reply"
    assert "backend unavailable" in result["error"]


def test_webui_test_chat_uses_the_same_relaxed_quality_mode_as_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    finalized: list[bool] = []

    class ToolReplyEngine:
        def __init__(self, config) -> None:
            self.config = config

        async def _reply_with_guarded_api(self, *args, **kwargs) -> str:
            return "联网结果第一条。\n联网结果第二条。\n联网结果第三条。\n来源链接。"

        def _finalize_reply(
            self,
            conversation_id: str,
            text: str,
            reply: str,
            *,
            strict_quality: bool = True,
        ) -> str:
            finalized.append(strict_quality)
            if strict_quality:
                raise RuntimeError("工具型回复被误判为长段说明")
            return reply

        def _fallback_reply(self, conversation_id: str, text: str) -> str:
            return "fallback reply"

    monkeypatch.setattr(webui_server, "AtriReplyEngine", ToolReplyEngine)
    config = BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="mention",
        openai_api_key="test-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temperature=0.8,
        max_tokens=350,
        memory_path=tmp_path / "users.json",
        human_reply_pipeline_enabled=True,
    )

    result = asyncio.run(webui_server.test_chat(config, "查一下今天的新闻"))

    assert finalized == [False]
    assert result["used_ai"] is True
    assert "联网结果第一条" in result["reply"]


def test_voice_preview_enables_safe_best_effort_quality_fallback() -> None:
    options = webui_server._voice_preview_synthesis_options(
        {
            "original_clip_enabled": True,
            "quality_gate_enabled": True,
            "quality_max_error_rate": 0.12,
            "quality_retries": 1,
        }
    )

    assert options["quality_gate"] is True
    assert options["quality_max_error_rate"] == 0.12
    assert options["allow_best_effort"] is True


def test_runtime_status_keeps_webui_contract(monkeypatch) -> None:
    snapshots: list[bool] = []

    def fake_tcp_rows():
        snapshots.append(True)
        return [
            {"local_port": 8765, "remote_port": 0, "state": "LISTENING", "pid": 100},
            {"local_port": 8765, "remote_port": 59351, "state": "ESTABLISHED", "pid": 100},
        ]

    monkeypatch.setattr("atri_qq_bot.runtime.control.tcp_rows", fake_tcp_rows)
    monkeypatch.setattr(
        "atri_qq_bot.runtime.control._recent_napcat_state",
        lambda: {"state": "connected", "detail": "NapCat 已连接"},
    )

    config = BotConfig(
        bot_qq=100000001,
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
    assert status["voice"] is False
    assert status["onebot"] == "ws://127.0.0.1:8765/onebot"
    assert status["webui_url"] == "http://127.0.0.1:8787"
    assert snapshots == [True]


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


def test_sticker_admin_lists_flat_root_images(tmp_path: Path, monkeypatch) -> None:
    sticker_root = tmp_path / "聊天表情"
    sticker_root.mkdir()
    (sticker_root / "调皮.gif").write_bytes(b"GIF89a")
    monkeypatch.setattr("atri_webui.sticker_admin.STICKER_ROOT", sticker_root)

    payload = sticker_summary()

    assert payload["path"] == str(sticker_root)
    assert payload["folders"][0]["name"] == "根目录"
    assert payload["folders"][0]["files"][0]["name"] == "调皮.gif"


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
