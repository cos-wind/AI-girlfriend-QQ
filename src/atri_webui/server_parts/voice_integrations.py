from __future__ import annotations

import json
import time
from typing import Any

def _voice_preview_synthesis_options(behavior: dict[str, Any]) -> dict[str, Any]:
    return _voice_preview_synthesis_options_for_mode(behavior, "strict")


def _voice_preview_synthesis_options_for_mode(
    behavior: dict[str, Any], mode: str = "strict"
) -> dict[str, Any]:
    fast = str(mode or "strict").strip().lower() in {"fast", "preview", "quick"}
    return {
        "prefer_original": bool(behavior.get("original_clip_enabled", True)),
        "quality_gate": (
            False if fast else bool(behavior.get("quality_gate_enabled", True))
        ),
        "quality_max_error_rate": float(
            behavior.get("quality_max_error_rate", 0.22)
        ),
        "quality_retries": 0 if fast else int(behavior.get("quality_retries", 1) or 0),
        # A preview should expose a safe, intelligible candidate even when ASR
        # differs slightly on names or non-Chinese text. The voice service still
        # rejects empty, badly truncated, or high-error candidates.
        "allow_best_effort": True,
    }


_TRANSLATION_LANGUAGES = {
    "zh": "简体中文",
    "en": "English",
    "ja": "日本語",
}


def _detect_translation_source(text: str) -> str:
    if any("\u3040" <= char <= "\u30ff" for char in text):
        return "ja"
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return "zh"
    if any(char.isalpha() for char in text):
        return "en"
    return "auto"


def _extract_translation(raw: str) -> str:
    value = str(raw or "").strip()
    if value.startswith("```"):
        value = value.strip("`").strip()
        if value.lower().startswith("json"):
            value = value[4:].strip()
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        value = str(parsed.get("translation") or parsed.get("text") or "").strip()
    value = value.strip().strip('"').strip()
    if not value or "未翻译" in value:
        raise ValueError("翻译服务没有返回有效译文")
    return value


async def translate_voice_text(config: BotConfig, text: str, target_language: str) -> dict[str, Any]:
    import httpx

    source_text = str(text or "").strip()
    target = str(target_language or "").strip().lower()
    if not source_text:
        raise ValueError("请输入要翻译的文本")
    if target not in _TRANSLATION_LANGUAGES:
        raise ValueError("目标语言只支持中文、英文或日文")
    source = _detect_translation_source(source_text)
    if source == target:
        return {"text": source_text, "source_language": source, "target_language": target}
    if not config.openai_api_key:
        raise ValueError("未配置聊天模型 API Key，无法自动翻译")
    prompt = (
        f"把下面文本翻译成{_TRANSLATION_LANGUAGES[target]}。保持原意、语气和称呼，适合直接用于语音合成。"
        "只返回译文，不要解释，不要引号，不要补充内容。\n\n"
        f"原文（语言代码：{source}）：\n{source_text}"
    )
    payload = {
        "model": config.openai_model,
        "messages": [
            {
                "role": "system",
                "content": "你是准确、克制的语音文案翻译器。不要改变人名、语气或句意。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": max(120, min(400, int(config.max_tokens))),
    }
    if (
        "api.deepseek.com" in str(config.openai_base_url).casefold()
        and str(config.openai_model).strip().casefold() in {"deepseek-v4-flash", "deepseek-v4-pro"}
    ):
        payload["thinking"] = {"type": "disabled"}
    started_at = time.perf_counter()
    async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=5.0)) as client:
        response = await client.post(
            f"{config.openai_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {config.openai_api_key}"},
            json=payload,
        )
        response.raise_for_status()
    data = response.json()
    raw = str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    translated = _extract_translation(raw)
    return {
        "text": translated,
        "source_language": source,
        "target_language": target,
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000),
    }

