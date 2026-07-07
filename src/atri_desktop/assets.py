from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ASSET_ROOT = Path(__file__).resolve().parent / "assets"
ASSET_DIR = ASSET_ROOT / "expressions"
APP_ICON_PATH = ASSET_ROOT / "atri-desktop-pet.ico"


@dataclass(frozen=True)
class Expression:
    key: str
    label: str
    filename: str
    message: str

    @property
    def path(self) -> Path:
        return ASSET_DIR / self.filename


EXPRESSIONS: tuple[Expression, ...] = (
    Expression("idle", "待机", "idle.png", "亚托莉待机中。右键可以启动或管理服务。"),
    Expression("happy", "开心", "happy.png", "哼哼，高性能亚托莉状态良好。"),
    Expression("idea", "灵感", "idea.png", "有主意了。需要我帮你启动后台吗？"),
    Expression("surprised", "惊讶", "surprised.png", "诶？状态好像需要确认一下。"),
    Expression("sleepy", "困困", "sleepy.png", "有点困，但还能继续守着。"),
    Expression("goodnight", "晚安", "goodnight.png", "晚安模式启动。"),
    Expression("snack", "吃点心", "snack.png", "补给完成，继续前进。"),
    Expression("cry", "委屈", "cry.png", "呜，命令失败了，先看一下提示。"),
)

EXPRESSION_BY_KEY = {expression.key: expression for expression in EXPRESSIONS}
DEFAULT_EXPRESSION = EXPRESSION_BY_KEY["idle"]


def expression_for_status(atri_running: bool, napcat_connected: bool) -> Expression:
    if atri_running and napcat_connected:
        return EXPRESSION_BY_KEY["happy"]
    if atri_running:
        return EXPRESSION_BY_KEY["idea"]
    return DEFAULT_EXPRESSION
