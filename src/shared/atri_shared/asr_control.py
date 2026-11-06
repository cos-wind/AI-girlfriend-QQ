"""Manual ASR residency on the configured local speech service."""
from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import service_control


def status() -> dict[str, Any]:
    return service_control.voice_service_status()


def control(action: str) -> dict[str, Any]:
    if action not in {"start", "stop"}:
        raise ValueError("不支持的识别模型操作")
    current = status()
    if action == "start" and not current["running"]:
        started = service_control.start_voice_service()
        if not started.get("ok"):
            raise RuntimeError(started.get("message") or "语音服务启动失败")
        current = status()
    if not current["running"] and action == "stop":
        return {"ok": True, "status": current, "message": "语音服务未运行，识别模型已释放"}
    if not current["available"]:
        raise RuntimeError("端口未确认是 ATRI 语音服务，请在语音服务页检查端口")
    if not current.get("asr", {}).get("model_control"):
        raise RuntimeError("当前语音服务是旧版本，请在“语音服务”页停止并重新启动服务，再开启识别模型")
    request = Request(
        current["url"] + "/v1/asr/model",
        data=json.dumps({"action": action}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        # Loading is bounded by the worker deadline plus the inference queue.
        with urlopen(request, timeout=450) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            message = json.loads(exc.read().decode("utf-8")).get("error")
        except (ValueError, UnicodeError):
            message = None
        raise RuntimeError(message or f"识别模型操作失败（HTTP {exc.code}）") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("识别模型操作未完成，请刷新状态确认；可在语音服务页查看日志") from exc
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError("识别模型操作失败，请刷新状态或查看语音服务日志")
    current["asr"] = result["asr"]
    return {"ok": True, "status": current, "message": (
        "识别模型已启动并保持加载，聊天、QQ 和已接入的游戏可复用" if action == "start"
        else "识别模型已释放，语音合成服务继续运行；下次识别将按需加载"
    )}
