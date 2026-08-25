# ATRI 开发者指南

这份文档面向本地开发、调试和故障排查。机器人由 NapCat/QQ 驱动，ATRI 只实现 OneBot v11 反向 WebSocket 服务；不要把 QQ 机器人逻辑和 NapCat 的 Node.js 运行时混在同一个 Python 进程里。

## 服务关系与启动顺序

```text
桌宠 / hidden_launcher
  ├─ core：ATRI Python 服务 :8765
  │    └─ 项目 WebUI :8787
  ├─ napcat：项目专用 NapCat + QQ
  │    └─ NapCat WebUI :6099
  ├─ optional：聊天连接后错峰启动 QZone Bridge :5700 / MaiBot :8001
  └─ 按需：Ollama :11434 / 语音服务 :8790
```

正确顺序是先让 ATRI 监听 `ws://127.0.0.1:8765/onebot`，再由独立模式恢复 NapCat；可选模块等待聊天链路，且彼此启动失败互不影响。NapCat 断线时 ATRI 不需要重启，会保持监听；恢复 QQ/NapCat 后应自动重连。

## 目录说明

| 路径 | 用途 |
|---|---|
| `src/atri_qq_bot/onebot/` | OneBot 入站事件、队列、防抖、回复和发送适配器 |
| `src/atri_qq_bot/persona/` | 人格、记忆、模型调用与回复守卫 |
| `src/atri_qq_bot/cognition/` | 持续目标、自我状态、情绪状态、能力契约与 LangGraph 认知图 |
| `src/atri_qq_bot/llm_tools/` | 联网、天气、网页、语音等工具调用 |
| `src/atri_qq_bot/runtime/` | 路径、运行状态、启动控制、统一日志与 NapCat WebUI 读取 |
| `src/atri_webui/` | 本机运维面板及 HTTP API |
| `src/atri_voice_service/` | 独立 ASR/TTS HTTP 服务 |
| `tools/` | 启动、桌宠、语音和环境检查脚本 |
| `data/` | 记忆、表情包、运行状态和可恢复数据 |
| `logs/` | 统一项目日志及各子系统日志 |

## 本机访问地址

| 服务 | 地址 | 用途 |
|---|---|---|
| ATRI OneBot | `ws://127.0.0.1:8765/onebot` | NapCat 反向 WS 客户端，不是浏览器页面 |
| 项目 WebUI | `http://127.0.0.1:8787` | 模型、记忆、语音、评测、群聊总结和状态 |
| NapCat WebUI | `http://127.0.0.1:6099/webui?token=…` | QQ/NapCat 配置与实时日志 |
| QZone Bridge（可选） | `http://127.0.0.1:5700` | WebUI 人工读取、点赞和评论 QQ 空间动态 |
| 语音服务 | `http://127.0.0.1:8790/health` | 健康检查 |
| Ollama | `http://127.0.0.1:11434` | 本地模型服务 |

## 认知内核

认知内核当前采用安全的影子运行：OneBot 收到消息并完成引用、图片与文档解析后，
将同一份规范化输入交给认知图；认知图维护用户目标、上下文关系、心情、自我状态和
能力提案，但不会发送消息或执行带副作用的工具。原有稳定回复链路继续负责实际回复，
同时只读使用上一轮的心情、目标与共同经历来保持人格连续性。

- 状态数据库：`data/cognition/state.sqlite3`（SQLite WAL）。
- 影子决策：`logs/cognition-shadow.jsonl`。
- 与现有回复的对照：`logs/cognition-comparison.jsonl`。
- WebUI 顶部状态栏会显示“认知内核 / 影子运行”和当前思维线程数。
- 每个私聊用户拥有独立线程；群聊按 `group:{群号}:user:{用户号}` 隔离个人状态。

影子状态属于工作记忆，不会直接写入 L1/L2/L3。只有经过长期记忆提取器验证的稳定
用户事实才进入人物档案，避免把临时情绪、错误工具提案或模型猜测污染长期记忆。

NapCat Token 从其 `config/webui.json` 读取。项目 WebUI 的“测试 → 开发者状态与访问入口”会提供 MaiBot（默认 `http://127.0.0.1:8001`）和 NapCat 的本机链接。MaiBot 是独立服务；当前 ATRI WebUI（8787）不会伪装成 MaiBot。Token 相当于管理密码，不能提交到 Git、截图或发送给他人。

## 从克隆到调试

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe tools\check_env.py
.\.venv\Scripts\python.exe -m atri_qq_bot
```

日常使用仍推荐桌宠菜单的“启动亚托莉”。前台运行 `python -m atri_qq_bot` 时会打印 NapCat WebUI 地址；后台运行时请从项目 WebUI 的“开发”页打开。

## 日志与调试

- 统一日志：`logs/project-YYYY-MM-DD.log`，级别由 `.env` 的 `LOG_LEVEL` 控制（`DEBUG`、`INFO`、`WARNING`、`ERROR`）。
- WebUI 的“评测 → 评测看板”每 3 秒读取一次统一日志，适合查看连接、消息决策、评测任务和 OneBot action。
- 原始业务日志仍保留：`onebot-events.log`、`reply-events.jsonl`、`llm-tools.jsonl`、`vision-events.jsonl`、`voice-events.log`。
- 日志不会写入聊天正文、API Key 或 NapCat Token。

## 常见问题

### NapCat 断开

1. 打开项目 WebUI → 开发，确认 8765 正在监听、NapCat WebUI 链接是否可访问。
2. 在 NapCat WebUI 检查 OneBot v11 WebSocket Client：地址必须为 `ws://127.0.0.1:8765/onebot`。
3. 若 QQ 已掉线，重新登录 QQ/NapCat；ATRI 保持运行时通常会自动重连。
4. 若 8765 未监听，使用桌宠启动，或前台执行 `python -m atri_qq_bot` 查看错误。

### 端口冲突或 WebUI 无法打开

运行 `python tools/check_env.py`。若 8787 被占用，调整 `.env` 的 `WEBUI_PORT`；6099 属于 NapCat，请在其 `webui.json` 中检查 `disableWebUI`、端口和 Token。

### Token 失效或无法登录 WebUI

不要在项目 `.env` 保存 NapCat Token。直接打开 NapCat 安装目录 `config/webui.json`，确认 Token；改动 NapCat 配置后重启 NapCat/QQ。

### 依赖缺失

先运行 `python tools/check_env.py`，再执行 `python -m pip install -r requirements.txt`。语音/歌唱的隔离运行时有各自依赖，不应安装进主 `.venv`。
