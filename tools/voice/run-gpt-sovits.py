"""直接在前台拉起 GPT-SoVITS api_v2（9880）的启动器，绕过 `Start-Process`。

为什么需要它
------------
`tools/voice/start-gpt-sovits.ps1` 用 `Start-Process` 拉分离进程，有两个坑：

1. **环境块里 `Path` 与 `PATH` 同时存在时 `Start-Process` 直接抛异常**
   （PowerShell 5.1 把进程环境拷进一个大小写不敏感字典）：

       Start-Process : 已添加项。字典中的关键字:"Path"所添加的关键字:"PATH"

   Git Bash / 某些宿主 shell 导出的就是大写 `PATH`，于是脚本在
   `$Process = Start-Process ...` 这一行崩掉，9880 永远起不来，
   语音服务只会回一句「GPT-SoVITS 按需启动失败」。本项目从桌面
   快捷方式（explorer 环境）启动时不会触发，所以只在自动化里暴露。
2. 即使拉起成功，`Start-Process` 出来的分离进程在后台任务结束时会**被一并回收**
   （与 `start-voice-service.ps1` 同一现象）。

本脚本把环境准备照抄 ps1（配置 yaml、各目录 junction、PYTHONUTF8 / NLTK_DATA /
HF_HOME / G2PW CPU 等），然后**前台**执行 api_v2.py —— 由调用方用后台常驻任务
托住生命周期，不依赖 Start-Process。

用法
----
    python tools/voice/run-gpt-sovits.py            # 前台运行，Ctrl-C 退出
    python tools/voice/run-gpt-sovits.py --port 9880

⚠️ 语音服务（8790）会先探测 9880；若本脚本已把 9880 拉起，服务就直接复用，
   不会再走它自己那条会崩的 `_launch_gpt_sovits()` 路径。
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = PROJECT_DIR / "data" / "runtime" / "gpt-sovits"
SOURCE_ROOT = RUNTIME_ROOT / "source"
LOG_DIR = PROJECT_DIR / "logs"

MODELS_ROOT = Path(os.environ.get("ASCII_ATRI_MODELS_ROOT") or PROJECT_DIR / "models")
VOICE_MODELS = MODELS_ROOT / "voice"
BASE_MODELS = VOICE_MODELS / "base" / "gpt-sovits" / "pretrained_models"
LEGACY_CANDIDATE = VOICE_MODELS / "candidates" / "2dipw-atri-gpt-sovits"
V2PRO_CANDIDATE = VOICE_MODELS / "candidates" / "atri-official-v2pro-curated"

# 启动时先装进来的权重；之后语音服务会用 set_gpt_weights / set_sovits_weights 按档案切换。
INITIAL_GPT = BASE_MODELS / "s1v3.ckpt"
INITIAL_SOVITS = V2PRO_CANDIDATE / "atri-official-v2pro-curated_e1_s884.pth"
INITIAL_VERSION = "v2Pro"


def port_open(port: int) -> bool:
    probe = socket.socket()
    probe.settimeout(0.6)
    try:
        return probe.connect_ex(("127.0.0.1", port)) == 0
    finally:
        probe.close()


CANONICAL_NAMES = {
    "PATH": "Path",
    "PYTHONPATH": "PYTHONPATH",
    "NLTK_DATA": "NLTK_DATA",
    "HF_HOME": "HF_HOME",
    "PYTHONUTF8": "PYTHONUTF8",
}


def clean_env() -> dict[str, str]:
    """把环境变量按大小写去重，只保留一份 —— 正是 `Start-Process` 崩掉的那个原因。

    同名不同大小写的键（`Path` / `PATH`）在 Windows 上本就是同一个变量，
    这里统一成规范写法。
    """
    merged: dict[str, str] = {}
    for key, value in os.environ.items():
        canonical = CANONICAL_NAMES.get(key.upper(), key)
        merged.setdefault(canonical, value)
    return merged


def ensure_links() -> None:
    source_pretrained = SOURCE_ROOT / "GPT_SoVITS" / "pretrained_models"
    source_pretrained.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("chinese-roberta-wwm-ext-large", "chinese-hubert-base", "fast_langdetect", "sv"):
        link = source_pretrained / name
        target = BASE_MODELS / name
        if not link.exists() and target.exists():
            subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(target)], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    g2pw_link = SOURCE_ROOT / "GPT_SoVITS" / "text" / "G2PWModel"
    g2pw_target = VOICE_MODELS / "base" / "gpt-sovits" / "G2PWModel"
    if not g2pw_link.exists() and g2pw_target.exists():
        subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(g2pw_link), str(g2pw_target)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def write_config() -> Path:
    config_path = RUNTIME_ROOT / "atri-tts-infer.yaml"
    config = (
        "custom:\n"
        f"  bert_base_path: {(BASE_MODELS / 'chinese-roberta-wwm-ext-large').as_posix()}\n"
        f"  cnhuhbert_base_path: {(BASE_MODELS / 'chinese-hubert-base').as_posix()}\n"
        "  device: cuda\n"
        "  is_half: true\n"
        f"  t2s_weights_path: {INITIAL_GPT.as_posix()}\n"
        f"  version: {INITIAL_VERSION}\n"
        f"  vits_weights_path: {INITIAL_SOVITS.as_posix()}\n"
    )
    config_path.write_text(config, encoding="utf-8")
    return config_path


def main() -> int:
    parser = argparse.ArgumentParser(description="前台启动 GPT-SoVITS api_v2")
    parser.add_argument("--port", type=int, default=9880)
    args = parser.parse_args()

    if port_open(args.port):
        print(f"[skip] {args.port} 已在监听，不重复启动。")
        return 0

    python = RUNTIME_ROOT / ".venv" / "Scripts" / "python.exe"
    api = SOURCE_ROOT / "api_v2.py"
    if not python.is_file() or not api.is_file():
        print(f"[错误] 运行时缺失: {python} / {api}")
        return 1

    ensure_links()
    config_path = write_config()

    env = clean_env()
    env.update(
        {
            "PYTHONUTF8": "1",
            "NLTK_DATA": str(RUNTIME_ROOT / ".venv" / "nltk_data"),
            "HF_HOME": str(VOICE_MODELS / "huggingface"),
            "ATRI_G2PW_FORCE_CPU": "true",
            "PYTHONPATH": str(PROJECT_DIR / "tools" / "voice" / "compat"),
            # 用规范写法 "Path"，避免再造出一个大小写重复键。
            "Path": str(SOURCE_ROOT) + os.pathsep + env.get("Path", ""),
        }
    )

    print(f"[launcher] api_v2.py 端口={args.port} 配置={config_path}", flush=True)
    print(f"[launcher] 日志 → {LOG_DIR / 'gpt-sovits.log'}", flush=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (
        (LOG_DIR / "gpt-sovits.log").open("ab") as out,
        (LOG_DIR / "gpt-sovits-error.log").open("ab") as err,
    ):
        completed = subprocess.run(
            [str(python), "api_v2.py", "-a", "127.0.0.1", "-p", str(args.port), "-c", str(config_path)],
            cwd=str(SOURCE_ROOT),
            env=env,
            stdout=out,
            stderr=err,
        )
    return int(completed.returncode)


if __name__ == "__main__":
    sys.exit(main())
