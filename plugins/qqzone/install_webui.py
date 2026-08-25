"""将 QQ动态路由挂载到 MaiBot WebUI。

用法：python plugins/qqzone/install_webui.py [MaiBot根目录]
卸载：python plugins/qqzone/install_webui.py [MaiBot根目录] --uninstall
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


IMPORT_BLOCK = """# qqzone-webui:import:start
from plugins.qqzone.webui_router import router as qqzone_router
# qqzone-webui:import:end
"""
ROUTE_BLOCK = """# qqzone-webui:route:start
router.include_router(qqzone_router)
# qqzone-webui:route:end
"""


def _remove_block(text: str, start: str, end: str) -> str:
    while start in text:
        before, rest = text.split(start, 1)
        if end not in rest:
            raise RuntimeError(f"发现不完整的 QQ动态补丁标记：{start.strip()}")
        _, after = rest.split(end, 1)
        text = before + after.lstrip("\r\n")
    return text


def uninstall_text(text: str) -> str:
    text = _remove_block(text, "# qqzone-webui:import:start", "# qqzone-webui:import:end")
    return _remove_block(text, "# qqzone-webui:route:start", "# qqzone-webui:route:end")


def install_text(text: str) -> str:
    clean = uninstall_text(text)
    import_anchor = 'logger = get_logger("webui.api")'
    route_anchor = "router.include_router(plugin_router)"
    if import_anchor not in clean:
        raise RuntimeError("无法定位 WebUI import 区域；当前 MaiBot 版本可能不兼容")
    if route_anchor not in clean:
        raise RuntimeError("无法定位插件路由注册点；当前 MaiBot 版本可能不兼容")
    clean = clean.replace(import_anchor, IMPORT_BLOCK + "\n" + import_anchor, 1)
    clean = clean.replace(route_anchor, route_anchor + "\n" + ROUTE_BLOCK.rstrip(), 1)
    return clean


def write_atomic(path: Path, text: str) -> None:
    temp = path.with_suffix(path.suffix + ".qqzone.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="安装 ATRI QQ动态的 MaiBot WebUI 路由")
    parser.add_argument("maibot_root", nargs="?", default=".", help="MaiBot 根目录")
    parser.add_argument("--uninstall", action="store_true", help="移除路由补丁")
    args = parser.parse_args()

    root = Path(args.maibot_root).expanduser().resolve()
    target = root / "src" / "webui" / "routes.py"
    plugin = root / "plugins" / "qqzone" / "webui_router.py"
    if not target.is_file():
        parser.error(f"不是有效的 MaiBot 根目录：找不到 {target}")
    if not args.uninstall and not plugin.is_file():
        parser.error(f"插件未复制完整：找不到 {plugin}")

    original = target.read_text(encoding="utf-8")
    updated = uninstall_text(original) if args.uninstall else install_text(original)
    if updated == original:
        print("QQ动态 WebUI 路由无需变更。")
        return 0

    backup = target.with_suffix(target.suffix + ".before-qqzone.bak")
    if not backup.exists():
        shutil.copy2(target, backup)
    write_atomic(target, updated)
    action = "已卸载" if args.uninstall else "已安装"
    print(f"{action} QQ动态 WebUI 路由：{target}")
    print(f"原文件备份：{backup}")
    print("请重启 MaiBot WebUI。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
