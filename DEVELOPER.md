# Qbot v0.5 开发说明

## 范围与入口

发布内容包括 `atri_qq_bot`、`atri_webui`、`atri_shared`、可选的 `atri_voice_service` 及必要脚本。QQ 启动入口是 `python -m atri_qq_bot` 或 `atri-qq-bot`；OneBot 主循环同时启动 Qbot WebUI，不要求桌面 Core API。

源码根目录由 `atri_runtime.resource_root()` 定位。默认用户数据与 `.env` 位于项目目录，可用 `ATRI_QBOT_USER_DIR` 指定独立的数据根目录；提示词和工具仍从源码目录读取。Windows 辅助启动器主要面向项目目录内的 `.venv` 部署。

## 模块分工

| 位置 | 职责 |
| --- | --- |
| `onebot/` | OneBot 连接、账号校验、事件解析和发送 |
| `application/`、`persona/`、`llm_tools/` | 对话编排、角色输出与工具执行 |
| `accounts/` | 账号注册、运行账号与账号数据布局 |
| `memory/`、`retrieval/`、`knowledge/` | 记忆持久化、检索和资料归档 |
| `music/library.py` | 本层成品歌曲清单与导入 |
| `music/session.py` | 请求、选歌、确认、取消和会话过期 |
| `onebot/server_parts/server_delivery.py` | QQ 点歌发送链路 |
| `atri_webui/` | 配置页面和配套 HTTP API |
| `atri_shared/` | 配置、NapCat 登录、模型档案与服务控制 |
| `atri_voice_service/` | 可选 ASR / TTS 后端；QQ 成品点歌不依赖它 |

## 检查

```powershell
python -m pip install -e ".[dev]"
python -m compileall -q src tools
python -m pytest -q
```

也可用 `uv sync --locked --extra dev` 安装锁定环境。测试应使用临时目录、模拟模型和模拟 OneBot；测试无需真实密钥和 QQ 登录。不要在测试里启动、停止开发机上的 QQ、NapCat 或模型服务。

单独检查点歌可运行 `python -m pytest -q tests/test_delivery_music.py tests/test_singing_webui.py`。语音测试验证配置与协议等可隔离行为，无法替代实际音色、模型性能和 QQ 语音投递的设备实测。

## 发布边界

公开提交仅包含源代码、脱敏样例、文档、依赖声明和测试。不要提交 `.env`、`data/` 中的运行文件、日志、账号历史、QQ/NapCat 程序、歌曲、参考音频、模型、本地虚拟环境或外部工程。发行目录与日常运行目录应分开核验，提交前检查暂存清单和秘密扫描结果。
