"""ATRI 启动前环境自检（不会启动、停止或修改任何服务）。

执行：.venv\\Scripts\\python.exe tools\\check_env.py
它检查 Python、核心依赖、.env、关键端口和 NapCat WebUI 配置，并给出
可操作的中文提示，适合在“启动失败”前先运行一次。
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_MODULES = {
    "httpx": "HTTP/模型接口",
    "websockets": "OneBot 反向 WebSocket",
    "dotenv": ".env 配置加载",
    "PIL": "图片预处理",
    "pypdf": "PDF 解析",
    "rapidocr": "OCR 识别",
    "onnxruntime": "本地 OCR 推理",
}
PORTS = {8765: "ATRI OneBot", 8787: "项目 WebUI", 8790: "语音服务", 6099: "NapCat WebUI", 11434: "Ollama"}


def main() -> int:
    problems: list[str] = []
    print("== ATRI 开发环境检查 ==")
    if sys.version_info < (3, 11):
        problems.append(f"Python 版本过低：当前 {sys.version.split()[0]}，需要 3.11+")
    else:
        print(f"[OK] Python {sys.version.split()[0]}")

    for module, purpose in CORE_MODULES.items():
        if importlib.util.find_spec(module) is None:
            problems.append(f"缺少依赖 {module}（{purpose}）；运行 pip install -r requirements.txt")
        else:
            print(f"[OK] {module}：{purpose}")

    env_path = ROOT / ".env"
    if not env_path.exists():
        problems.append("未找到 .env；请从 .env.example 复制后填写 BOT_QQ 和模型配置")
    else:
        print("[OK] .env 已存在")

    for port, name in PORTS.items():
        state = "正在监听" if _port_open(port) else "未监听（启动前正常）"
        print(f"[INFO] {name} :{port} {state}")

    webui = _napcat_webui_config()
    if webui is None:
        problems.append("未找到 NapCat webui.json；请确认 NAPCAT_DIR 或 NapCat 安装目录")
    elif bool(webui.get("disableWebUI", False)):
        problems.append("NapCat WebUI 已禁用；请在 webui.json 中将 disableWebUI 改为 false")
    else:
        print(f"[OK] NapCat WebUI 已配置：port={webui.get('port', 6099)}，Token={'已设置' if webui.get('token') else '未设置'}")

    if problems:
        print("\n发现以下问题：")
        for problem in problems:
            print(f"[WARN] {problem}")
        return 1
    print("\n[OK] 环境检查通过。可启动桌宠，或运行 python -m atri_qq_bot。")
    return 0


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def _napcat_webui_config() -> dict[str, object] | None:
    roots = [Path(r"D:\Tools\NapCat\OneKey"), Path.home() / "AppData" / "Local" / "NapCat"]
    for root in roots:
        for path in root.glob("NapCat*.Shell/versions/*/resources/app/napcat/config/webui.json"):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return None


if __name__ == "__main__":
    raise SystemExit(main())
