from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


PROFILE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,48}$")


@dataclass(frozen=True)
class VoiceProfile:
    id: str
    display_name: str
    tts_provider: str = "gpt_sovits"
    api_url: str = "http://127.0.0.1:9880/tts"
    reference_audio: str = ""
    prompt_text: str = ""
    prompt_language: str = "ja"
    text_language: str = "auto"
    emotion_references: dict[str, str] = field(default_factory=dict)
    emotion_prompt_texts: dict[str, str] = field(default_factory=dict)
    emotion_prompt_languages: dict[str, str] = field(default_factory=dict)
    auxiliary_references: list[str] = field(default_factory=list)
    language_references: dict[str, str] = field(default_factory=dict)
    language_prompt_texts: dict[str, str] = field(default_factory=dict)
    language_prompt_languages: dict[str, str] = field(default_factory=dict)
    model_id: str = ""
    model_version: str = ""
    gpt_weights: str = ""
    sovits_weights: str = ""
    source: str = ""
    license: str = ""

    @property
    def ready(self) -> bool:
        paths = [self.reference_audio]
        if self.gpt_weights or self.sovits_weights:
            paths.extend((self.gpt_weights, self.sovits_weights))
        return bool(self.api_url and all(path and Path(path).is_file() for path in paths))

    def public_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ready": self.ready}


class VoiceProfileStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def ensure_default(self) -> VoiceProfile:
        try:
            return self.load("atri")
        except FileNotFoundError:
            profile = VoiceProfile(id="atri", display_name="亚托莉")
            self.save(profile)
            return profile

    def load(self, profile_id: str) -> VoiceProfile:
        path = self._profile_path(profile_id)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("语音档案格式无效")
        return profile_from_dict(raw, expected_id=profile_id)

    def list(self) -> list[VoiceProfile]:
        if not self.root.exists():
            return []
        profiles: list[VoiceProfile] = []
        for path in sorted(self.root.glob("*/profile.json")):
            try:
                profiles.append(self.load(path.parent.name))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return profiles

    def save(self, profile: VoiceProfile) -> Path:
        path = self._profile_path(profile.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(profile), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return path

    def _profile_path(self, profile_id: str) -> Path:
        if not PROFILE_ID_RE.fullmatch(str(profile_id or "")):
            raise ValueError("语音档案 ID 只能包含字母、数字、下划线和短横线")
        return self.root / profile_id / "profile.json"


def profile_from_dict(raw: dict[str, Any], expected_id: str | None = None) -> VoiceProfile:
    profile_id = str(raw.get("id") or expected_id or "").strip()
    if expected_id and profile_id != expected_id:
        raise ValueError("语音档案 ID 与目录不一致")
    if not PROFILE_ID_RE.fullmatch(profile_id):
        raise ValueError("语音档案 ID 无效")
    references = raw.get("emotion_references")
    return VoiceProfile(
        id=profile_id,
        display_name=str(raw.get("display_name") or profile_id).strip(),
        tts_provider=str(raw.get("tts_provider") or "gpt_sovits").strip().lower(),
        api_url=str(raw.get("api_url") or "").strip(),
        reference_audio=str(raw.get("reference_audio") or "").strip(),
        prompt_text=str(raw.get("prompt_text") or "").strip(),
        prompt_language=str(raw.get("prompt_language") or "ja").strip().lower(),
        text_language=str(raw.get("text_language") or "auto").strip().lower(),
        emotion_references={
            str(key).strip().lower(): str(value).strip()
            for key, value in (references.items() if isinstance(references, dict) else [])
            if str(value).strip()
        },
        emotion_prompt_texts=_normalized_string_map(raw.get("emotion_prompt_texts")),
        emotion_prompt_languages=_normalized_string_map(
            raw.get("emotion_prompt_languages")
        ),
        auxiliary_references=[
            str(item).strip()
            for item in (
                raw.get("auxiliary_references")
                if isinstance(raw.get("auxiliary_references"), list)
                else []
            )
            if str(item).strip()
        ][:8],
        language_references=_normalized_string_map(raw.get("language_references")),
        language_prompt_texts=_normalized_string_map(raw.get("language_prompt_texts")),
        language_prompt_languages=_normalized_string_map(raw.get("language_prompt_languages")),
        model_id=str(raw.get("model_id") or "").strip(),
        model_version=str(raw.get("model_version") or "").strip(),
        gpt_weights=str(raw.get("gpt_weights") or "").strip(),
        sovits_weights=str(raw.get("sovits_weights") or "").strip(),
        source=str(raw.get("source") or "").strip(),
        license=str(raw.get("license") or "").strip(),
    )


def _normalized_string_map(value: Any) -> dict[str, str]:
    return {
        str(key).strip().lower(): str(item).strip()
        for key, item in (value.items() if isinstance(value, dict) else [])
        if str(key).strip() and str(item).strip()
    }
