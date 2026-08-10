from __future__ import annotations

import json

from atri_qq_bot.config.schema import BotConfig
from atri_webui import config_admin
from atri_webui import model_profiles as model_profiles_module
from atri_webui.model_profiles import activate_model_profile, model_profiles_payload


def _config(tmp_path, enabled: bool = True) -> BotConfig:
    return BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="smart",
        openai_api_key="chat-key",
        openai_base_url="https://api.deepseek.com/v1",
        openai_model="deepseek-v4-flash",
        temperature=0.65,
        max_tokens=260,
        memory_path=tmp_path / "users.json",
        memory_vector_enabled=enabled,
        memory_embedding_model="bge-m3:latest",
        memory_embedding_base_url="http://127.0.0.1:11434",
    )


def test_embedding_profile_is_reported_as_current_and_active(tmp_path, monkeypatch) -> None:
    profile_path = tmp_path / "model_profiles.json"
    monkeypatch.setattr(model_profiles_module, "MODEL_PROFILE_PATH", profile_path)
    monkeypatch.setattr(model_profiles_module, "WEBUI_DIR", tmp_path)
    profile_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "id": "bge-local",
                        "name": "Local BGE",
                        "model_type": "embedding",
                        "provider": "Ollama",
                        "base_url": "http://127.0.0.1:11434/v1",
                        "model": "bge-m3:latest",
                        "api_key": "ollama",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = model_profiles_payload(_config(tmp_path))

    assert payload["active_ids"]["embedding"] == "bge-local"
    assert payload["current_by_type"]["embedding"]["enabled"] is True
    assert payload["current_by_type"]["embedding"]["model"] == "bge-m3:latest"


def test_activating_embedding_profile_writes_runtime_config(tmp_path, monkeypatch) -> None:
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
                        "id": "bge-local",
                        "name": "Local BGE",
                        "model_type": "embedding",
                        "provider": "Ollama",
                        "base_url": "http://127.0.0.1:11434/v1",
                        "model": "bge-m3:latest",
                        "api_key": "ollama",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    env_path.write_text("OPENAI_MODEL=deepseek-v4-flash\n", encoding="utf-8")

    activate_model_profile("bge-local")
    env = config_admin.read_env()

    assert env["MEMORY_RETRIEVAL_ENABLED"] == "true"
    assert env["MEMORY_VECTOR_ENABLED"] == "true"
    assert env["MEMORY_EMBEDDING_MODEL"] == "bge-m3:latest"
    assert env["MEMORY_EMBEDDING_BASE_URL"] == "http://127.0.0.1:11434"
