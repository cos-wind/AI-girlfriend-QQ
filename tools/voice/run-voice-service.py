"""无 PowerShell 环境下启动 atri_voice_service 的等价启动器。

背景
----
`tools/voice/start-voice-service.ps1` 是官方启动方式，但它用 `Start-Process` 拉起分离
进程；在某些宿主（后台任务 / 非交互会话）里，父调用一结束该子进程就会被回收，表现为
脚本刚打印 "ready" 端口就关闭。另外**从沙箱里启动会让服务自锁**：

    src/atri_qq_bot/runtime/inference_lock.py:158 _ticket_is_next 依赖 `ticket.unlink()`
    清理排队票据；子进程删不掉文件时，`acquire()` 中 `ticket.unlink` 抛的 OSError 被
    `except OSError` 吞掉，但此时 `self._stream` 已赋值且没有 `return` → 自持锁无限重试
    → 服务永久僵死（`/health` 秒回、合成永不返回、GPU 0%）。

所以本脚本用于「需要独立实例」的场景：在**非沙箱**环境里以前台方式运行服务，由调用方
用后台常驻任务托住进程生命周期。

首选仍是**让项目自己托管**——机器人 `atri_qq_bot` 起来后会自动拉起 8790，无需本脚本。

⚠️ 环境变量是本文件的副本，唯一权威仍是 `start-voice-service.ps1`；改 ps1 时请同步这里。

用法
----
    python tools/voice/run-voice-service.py
"""

from __future__ import annotations

import os
import runpy
import socket
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
MODELS_ROOT = Path(os.environ.get("ASCII_ATRI_MODELS_ROOT") or PROJECT_DIR / "models")
USERPROFILE = Path(os.environ.get("USERPROFILE", str(Path.home())))

modelscope_cache = MODELS_ROOT / "voice" / "modelscope"
sensevoice = modelscope_cache / "models" / "iic--SenseVoiceSmall" / "snapshots" / "master"
vad = (
    modelscope_cache
    / "models"
    / "iic--speech_fsmn_vad_zh-cn-16k-common-pytorch"
    / "snapshots"
    / "master"
)


def port_in_use(port: int) -> bool:
    probe = socket.socket()
    probe.settimeout(1.0)
    try:
        return probe.connect_ex(("127.0.0.1", port)) == 0
    finally:
        probe.close()


def main() -> int:
    src = str(PROJECT_DIR / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from atri_shared.voice_endpoint import local_voice_port, validate_port

    port = validate_port(os.environ.get("ATRI_VOICE_PORT") or local_voice_port())
    if port_in_use(port):
        print(f"[skip] 端口 {port} 已被占用，请检查现有服务或在软件中修改端口。")
        return 1

    os.environ.update(
        {
            "ATRI_VOICE_HOST": "127.0.0.1",
            "ATRI_VOICE_PORT": str(port),
            "MODELSCOPE_CACHE": str(modelscope_cache),
            "HF_HOME": str(MODELS_ROOT / "voice" / "huggingface"),
            "ATRI_ASR_PROVIDER": "sensevoice",
            "ATRI_ASR_MODEL": (
                str(sensevoice)
                if (sensevoice / "model.pt").is_file()
                else "iic/SenseVoiceSmall"
            ),
            "ATRI_ASR_DEVICE": "cpu",
            "ATRI_ASR_WORKER_IDLE_SECONDS": os.environ.get("ATRI_ASR_WORKER_IDLE_SECONDS", "60"),
            "ATRI_ASR_VAD_MODEL": (
                str(vad)
                if (vad / "model.pt").is_file()
                else "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
            ),
            "ATRI_ASR_PREPROCESS_ENABLED": "true",
            "ATRI_ASR_LEXICON_PATH": str(PROJECT_DIR / "data" / "voice" / "asr-hotwords.json"),
            "ATRI_ORIGINAL_VOICE_LIBRARY": str(USERPROFILE / "Music" / "ATRI训练音频素材"),
            "ATRI_ORIGINAL_CLIP_ENABLED": "true",
            "ATRI_TTS_QUALITY_GATE_ENABLED": "false",
            # ⚠️ 默认关闭预热。`app.py:130 prewarm_tts` 会持 `tts:prewarm` 租约去调
            # `ensure_gpt_sovits_runtime(timeout_seconds=120)`；只要 9880 侧还没真正
            # 把模型加载完（端口先于权重就绪），这个调用会长时间挂住并**一直占着推理锁**，
            # 表现就是 `/health` 秒回、`inference_resources.busy=true` 永不归位、任何
            # 合成请求排队超时。关掉预热后首条合成只是慢一点，但不会僵死。
            "ATRI_TTS_PREWARM_ENABLED": os.environ.get("ATRI_TTS_PREWARM_ENABLED", "false"),
            "ATRI_TTS_IDLE_SHUTDOWN_SECONDS": "0",
            "ATRI_TTS_TOTAL_TIMEOUT_SECONDS": "75",
            "ATRI_TTS_STARTUP_TIMEOUT_SECONDS": "45",
            "ATRI_TTS_QUALITY_MAX_ERROR_RATE": "0.22",
            "ATRI_TTS_QUALITY_RETRIES": "1",
            "ATRI_SINGING_ENABLED": "true",
            "ATRI_SINGING_PIPELINE_MANIFEST": str(
                PROJECT_DIR / "data" / "voice" / "singing-pipeline.json"
            ),
            "ATRI_SINGING_MAXIMUM_JOBS": "50",
        }
    )

    compat = str(PROJECT_DIR / "tools" / "voice" / "compat")
    existing = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = compat + (os.pathsep + existing if existing else "")

    os.chdir(PROJECT_DIR)
    src = str(PROJECT_DIR / "src")
    if src not in sys.path:
        sys.path.insert(0, src)

    print(f"[launcher] cwd={os.getcwd()}", flush=True)
    runpy.run_module("atri_voice_service", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
