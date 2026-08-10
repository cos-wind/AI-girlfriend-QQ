from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from atri_qq_bot.runtime.paths import VOICE_CACHE_DIR, VOICE_PROFILE_DIR, VOICE_ROOT
from atri_voice_service.profiles import VoiceProfile, VoiceProfileStore, profile_from_dict
from atri_voice_service.model_registry import install_candidate_profiles, load_voice_candidates
from atri_voice_service.asr_lexicon import load_lexicon_payload, save_lexicon
from atri_voice_service.tts_text import load_pronunciation_text, save_pronunciation_text


AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".ogg", ".m4a", ".aac"}
ASR_LEXICON_PATH = VOICE_ROOT / "asr-hotwords.json"
TTS_PRONUNCIATION_PATH = VOICE_ROOT / "tts-pronunciations.json"


def voice_profile_store() -> VoiceProfileStore:
    store = VoiceProfileStore(VOICE_PROFILE_DIR)
    store.ensure_default()
    install_candidate_profiles(store)
    return store


def voice_profiles_payload() -> list[dict[str, Any]]:
    return [profile.public_dict() for profile in voice_profile_store().list()]


def voice_candidates_payload() -> list[dict[str, Any]]:
    return [candidate.public_dict() for candidate in load_voice_candidates()]


def asr_lexicon_text() -> str:
    payload = load_lexicon_payload(ASR_LEXICON_PATH)
    lines = []
    for entry in payload["entries"]:
        aliases = ", ".join(entry["aliases"])
        lines.append(f"{entry['term']} = {aliases}" if aliases else str(entry["term"]))
    return "\n".join(lines)


def save_asr_lexicon_text(text: str) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        term, separator, raw_aliases = line.partition("=")
        aliases = (
            [item.strip() for item in raw_aliases.replace("，", ",").split(",") if item.strip()]
            if separator
            else []
        )
        entries.append({"term": term.strip(), "aliases": aliases})
    return save_lexicon(ASR_LEXICON_PATH, entries)


def tts_pronunciation_text() -> str:
    return load_pronunciation_text(TTS_PRONUNCIATION_PATH)


def save_tts_pronunciation_text(text: str) -> dict[str, Any]:
    return save_pronunciation_text(TTS_PRONUNCIATION_PATH, text)


def save_voice_profile(payload: dict[str, Any]) -> VoiceProfile:
    profile_id = str(payload.get("id") or "atri").strip()
    store = voice_profile_store()
    try:
        existing = store.load(profile_id)
    except FileNotFoundError:
        existing = VoiceProfile(id=profile_id, display_name=profile_id)
    merged = {
        **existing.public_dict(),
        **payload,
        "id": profile_id,
    }
    merged.pop("ready", None)
    profile = profile_from_dict(merged, expected_id=profile_id)
    store.save(profile)
    return profile


def save_reference_audio(profile_id: str, filename: str, data: bytes) -> VoiceProfile:
    suffix = Path(filename).suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        raise ValueError("参考音频只支持 wav/flac/mp3/ogg/m4a/aac")
    if not data:
        raise ValueError("参考音频为空")
    store = voice_profile_store()
    profile = store.load(profile_id)
    target_dir = VOICE_PROFILE_DIR / profile.id / "references"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"reference{suffix}"
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(target)
    updated = replace(profile, reference_audio=str(target.resolve()))
    store.save(updated)
    return updated


def save_test_audio(filename: str, data: bytes) -> Path:
    suffix = Path(filename).suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        raise ValueError("测试音频只支持 wav/flac/mp3/ogg/m4a/aac")
    if not data:
        raise ValueError("测试音频为空")
    VOICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = VOICE_CACHE_DIR / f"asr-test-{uuid4().hex}{suffix}"
    target.write_bytes(data)
    return target.resolve()


def save_singing_source_audio(filename: str, data: bytes) -> Path:
    suffix = Path(filename).suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        raise ValueError("导唱音频只支持 wav/flac/mp3/ogg/m4a/aac")
    if not data:
        raise ValueError("导唱音频为空")
    target_dir = VOICE_CACHE_DIR / "singing-sources"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"source-{uuid4().hex}{suffix}"
    target.write_bytes(data)
    return target.resolve()


def resolve_voice_audio(raw_path: str) -> Path | None:
    try:
        root = VOICE_ROOT.resolve()
        path = Path(raw_path).expanduser().resolve()
        path.relative_to(root)
    except (OSError, ValueError):
        return None
    if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
        return None
    return path
