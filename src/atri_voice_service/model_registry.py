from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .config import default_voice_models_root
from .profiles import VoiceProfile, VoiceProfileStore


@dataclass(frozen=True)
class VoiceCandidate:
    id: str
    display_name: str
    version: str
    source: str
    license: str
    languages: tuple[str, ...]
    gpt_weights: Path
    sovits_weights: Path
    reference_audio: Path
    prompt_text: str
    prompt_language: str
    emotion_references: dict[str, Path]
    verified: bool

    @property
    def ready(self) -> bool:
        return self.verified and all(
            path.is_file()
            for path in (self.gpt_weights, self.sovits_weights, self.reference_audio)
        )

    @property
    def profile_id(self) -> str:
        aliases = {
            "2dipw-atri-gpt-sovits": "atri-2dipw",
            "voidshine-atri-v2pro": "atri-voidshine",
        }
        return aliases.get(self.id, self.id)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "version": self.version,
            "source": self.source,
            "license": self.license,
            "languages": list(self.languages),
            "ready": self.ready,
        }


def candidate_root() -> Path:
    return default_voice_models_root() / "candidates"


def base_model_root() -> Path:
    return default_voice_models_root() / "base" / "gpt-sovits" / "pretrained_models"


def load_voice_candidates(root: Path | None = None) -> list[VoiceCandidate]:
    resolved_root = (root or candidate_root()).resolve()
    candidates: list[VoiceCandidate] = []
    if not resolved_root.is_dir():
        return candidates
    for manifest_path in sorted(resolved_root.glob("*/candidate.json")):
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            candidates.append(_candidate_from_manifest(raw, manifest_path.parent))
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return candidates


def install_candidate_profiles(store: VoiceProfileStore) -> list[VoiceProfile]:
    installed: list[VoiceProfile] = []
    for candidate in load_voice_candidates():
        profile_id = candidate.profile_id
        try:
            profile = store.load(profile_id)
        except FileNotFoundError:
            profile = VoiceProfile(
                id=profile_id,
                display_name=candidate.display_name,
                api_url="http://127.0.0.1:9880/tts",
                reference_audio=str(candidate.reference_audio),
                prompt_text=candidate.prompt_text,
                prompt_language=candidate.prompt_language,
                text_language="auto",
                model_id=candidate.id,
                model_version=candidate.version,
                gpt_weights=str(candidate.gpt_weights),
                sovits_weights=str(candidate.sovits_weights),
                source=candidate.source,
                license=candidate.license,
                emotion_references={
                    emotion: str(path) for emotion, path in candidate.emotion_references.items()
                },
            )
            store.save(profile)
        else:
            missing_references = {
                emotion: str(path)
                for emotion, path in candidate.emotion_references.items()
                if emotion not in profile.emotion_references and path.is_file()
            }
            if missing_references:
                profile = replace(
                    profile,
                    emotion_references={**profile.emotion_references, **missing_references},
                )
                store.save(profile)
        installed.append(profile)
    return installed


def _candidate_from_manifest(raw: dict[str, Any], directory: Path) -> VoiceCandidate:
    gpt_value = str(raw["gpt_weights"])
    if gpt_value.startswith("@official/"):
        gpt_weights = base_model_root() / gpt_value.removeprefix("@official/")
    else:
        gpt_weights = directory / gpt_value
    version = str(raw.get("declared_version") or "v1")
    if version == "unknown":
        version = "v1"
    raw_emotion_references = raw.get("emotion_references")
    emotion_references = {
        str(emotion).strip().lower(): (directory / str(filename)).resolve()
        for emotion, filename in (
            raw_emotion_references.items()
            if isinstance(raw_emotion_references, dict)
            else []
        )
        if str(filename).strip()
    }
    return VoiceCandidate(
        id=str(raw["id"]),
        display_name=str(raw["display_name"]),
        version=version,
        source=str(raw.get("source") or ""),
        license=str(raw.get("license") or ""),
        languages=tuple(str(item) for item in raw.get("declared_languages") or ()),
        gpt_weights=gpt_weights.resolve(),
        sovits_weights=(directory / str(raw["sovits_weights"])).resolve(),
        reference_audio=(directory / str(raw["reference_audio"])).resolve(),
        prompt_text=str(raw.get("prompt_text") or ""),
        prompt_language=str(raw.get("prompt_language") or "ja"),
        emotion_references=emotion_references,
        verified=bool(raw.get("verified")),
    )
