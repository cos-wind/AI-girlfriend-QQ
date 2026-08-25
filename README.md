# 亚托莉 QQ 陪伴机器人 — Atri QQ Bot

<p align="center">
  <strong>基于 OneBot/NapCat 协议的 AI 陪伴机器人</strong><br>
  RAG 记忆检索 · Function Calling · 联网搜索 · 语音/歌声 · 工具箱 · 桌宠 · Web 管理面板
</p>

---

## 版本与发布状态

| 分支 | 版本 | 状态与定位 |
|------|------|------------|
| `main` | **v0.4** | 当前默认分支，跟随最新稳定代码 |
| `v0.4` | **v0.4** | 当前发行版本，包含认知内核、评测、群聊总结与 QQ 空间扩展 |
| `v0.3` | **v0.3** | 上一代稳定版本：RAG 记忆、Agent 工具、语音/歌声与 WebUI |
| `v0.2` | **v0.2** | 包结构重构与 LLM Function Calling 工具系统 |
| `v0.1-original` | **v0.1** | 原始扁平文件版本，仅作历史存档 |

## v0.4 技术框架与版本变化

v0.4 在 v0.3 的聊天、RAG、工具调用和语音能力上，增加了“状态连续性—回复质量—外围能力”三条旁路，并把原先集中在少数大文件中的逻辑拆成可测试模块。核心原则是：实时回复链路优先可用，认知、评测、总结和自动化失败时可以独立降级。

### 技术栈总览

v0.4 的技术栈按职责分层如下：

- **运行时**：Python 3.11、`asyncio`、`python-dotenv`；负责异步任务、配置加载和后台服务生命周期。
- **QQ 接入**：NapCat / OneBot v11、`websockets` 14、反向 WebSocket；负责事件接收、会话排队、消息发送和健康检查。
- **应用编排**：`ConversationTurn`、Protocol collaborators、`TurnTrace`；固定“上下文 → Agent → 交付计划”的单轮事务边界。
- **回复引擎**：`AtriReplyEngine`、OpenAI-compatible API、Tool Registry；负责人格提示词、回复重写、Function Calling 和失败降级。
- **记忆检索**：JSON 事实源、SQLite FTS5、可选 Ollama `bge-m3`；负责分层记忆、语义召回、原作设定和用户上下文压缩。
- **认知内核**：LangGraph `StateGraph`、`CognitionKernel`、SQLite/WAL；负责理解、能力提案和状态演化，当前以 shadow mode 安全运行。
- **质量旁路**：`InsightsRuntime`、SQLite、LLM evaluator、`jieba`、可选 `sentence-transformers`；负责回复评测、群消息归档、主题聚类和周期报表。
- **Web 管理**：Python `ThreadingHTTPServer` + `asyncio`、模块化 `page/`；提供配置、记忆、模型、评测、群总结、音乐、语音和 QQ 空间页面。
- **语音与媒体**：本机 HTTP voice service、GPT-SoVITS、Edge-TTS、SenseVoice、Pillow、RapidOCR、pypdf、ffmpeg；支持 ASR/TTS、歌声工程、图片/OCR/PDF/视频处理。
- **资源治理**：跨进程文件锁、优先级队列、Ollama 按需启动/卸载；协调聊天、用户媒体、视觉和后台任务对 GPU/内存的竞争。

### v0.4 请求链路

```text
NapCat / OneBot
      │ 反向 WebSocket
      ▼
OneBotServer ── 会话队列 / 防抖 / 健康检查
      ▼
ConversationTurn
      ├─ ContextAssembler：记忆检索、视觉/文档/语音材料、人格上下文
      ├─ AgentRunner：AtriReplyEngine、LLM Tool Registry、工具回执
      └─ DeliveryPlanner：文本拆分、语音/图片/音乐动作、OneBot 投递
             │
             ├── CognitionKernel（LangGraph shadow state）
             └── InsightsRuntime（异步归档、评测、群聊总结）
```

### 相比 v0.3 的新增功能与技术优化

以下采用纵向说明，避免在窄屏、移动端或 GitHub 代码视图中出现宽表格裁切。

#### 1. 持续状态

- **v0.3**：主要依赖人格提示词、短期上下文和三层用户记忆。
- **v0.4**：新增 `src/atri_qq_bot/cognition/`。`CognitionKernel` 使用 LangGraph `StateGraph` 连接“理解”和“能力提案”节点，再由 `CognitionStateStore` 写入 SQLite/WAL。
- **优化结果**：目标、情绪、自我经历和未解决问题可以连续保存；当前只更新 shadow state，不越权发送消息或执行副作用。

#### 2. 单轮编排

- **v0.3**：上下文、模型调用和消息投递更多集中在 OneBot 服务中。
- **v0.4**：新增 `src/atri_qq_bot/application/turn.py`，把上下文组装、Agent 运行和交付计划固定成可追踪的事务顺序。
- **优化结果**：`ContextAssembler`、`AgentRunner`、`DeliveryPlanner` 通过 Protocol 解耦，模型、视觉和 OneBot 适配器可以替换并单独测试。

#### 3. 记忆与人格模块

- **v0.3**：记忆主要集中在 `memory.py` 和 `memory_parts/`。
- **v0.4**：拆分为 `memory/`、`persona/engine_*` 和规则模块。
- **优化结果**：加入记忆污染过滤、结构化观察、关系状态、回填和主动关怀规则，降低单体文件耦合。

#### 4. OneBot 稳定性

- **v0.3**：连接、事件、投递和主动规划集中在单体服务中。
- **v0.4**：拆到 `src/atri_qq_bot/onebot/server_parts/`，增加每会话队列、防抖合并、顺序投递、健康探测、视觉上下文 TTL 和超时降级。
- **优化结果**：慢模型或媒体任务不容易打乱同一会话的消息顺序。

#### 5. 回复质量与群聊总结

- **v0.3**：没有独立的系统化质量旁路。
- **v0.4**：新增 `src/atri_qq_bot/insights/`，使用 SQLite store、异步 evaluation worker、六维 LLM 评测、语义评分和群聊主题聚类。
- **优化结果**：评测、归档和总结在旁路运行，不阻塞主回复；WebUI 可以追踪质量趋势和总结报告。

#### 6. WebUI 架构

- **v0.3**：页面集中在 `src/atri_webui/page.py`，开发入口较重。
- **v0.4**：拆为 `page/body_*`、`page/script_*` 和 `server_parts/handler_*`。
- **优化结果**：评测、群聊总结、音乐、QQ 空间和用户目录页面可以独立扩展和回归测试。

#### 7. QQ 空间扩展

- **v0.3**：没有项目内 QQ 空间扩展边界。
- **v0.4**：新增 `plugins/qqzone/`、`qzone_admin.py` 和 `qzone_automation/`，通过本机 Bridge 执行，默认关闭。
- **优化结果**：Cookie 只保留在 Bridge；点赞和评论保留人工确认边界。

#### 8. 音乐与资源治理

- **v0.3**：已有语音/歌声能力，但运行入口和资源竞争更集中。
- **v0.4**：新增 `music/library.py`、`music/session.py`、运行时服务和跨进程推理锁；Ollama 按真实请求启动，推理完成后按配置释放模型。
- **优化结果**：降低聊天、视觉、embedding 和语音之间的 GPU 争用。

#### 9. 发布工程

- **v0.3**：本地配置、运行数据和源码边界不够清晰。
- **v0.4**：更新 `.env.example`、`.gitignore` 和 `uv.lock`，加入 LangGraph、SQLite checkpoint 及 Insights 可选依赖。
- **优化结果**：公开仓库只保留可复现的源码、文档和示例配置。

详细的评测、群聊总结和隐私配置见 [`docs/insights.md`](docs/insights.md)；语音运行时见 [`docs/voice.md`](docs/voice.md)。

---

## 小白启动方式

最简单：

1. 从桌宠菜单选择“启动亚托莉”，或运行 `tools\launch\qq_legacy\start-with-qq.vbs`。
2. 启动器先让 ATRI 监听 OneBot，再用独立隐藏进程恢复项目专用 NapCat/QQ。
3. QQ 空间 Bridge 和 MaiBot 属于可选模块，会在聊天核心之后错峰启动；Ollama 与语音服务按真实请求启动。
4. 如果 NapCat 掉线或 QQ 登录失效，请打开 NapCat WebUI 手动扫码登录；项目不会自动弹出二维码。
5. 用另一个 QQ 给机器人账号发送私聊消息测试。

第一次安装或需要重建 `.venv` 时运行 `tools\launch\atri\start-atri.bat`。正常启动不再执行依赖安装，也不会绕过统一启动器。若 `.env` 中 `QZONE_BRIDGE_ENABLED=true`，可选启动模式会检查并复用本机 QQ 空间 Bridge（5700 端口）。

停止机器人：

- 平时不用手动停止，关闭 QQ 即可。
- 如果需要彻底停止，可以运行项目根目录里的 `停止亚托莉.bat`。

NapCat 的 OneBot 反向 WebSocket 已经自动配置为：`ws://127.0.0.1:8765/onebot`。项目只有一个运行入口；已移除会重复安装依赖并直接启动主进程的旧 `run.ps1`。

这是一个最小可运行的 NapCat / OneBot v11 反向 WebSocket 机器人，用配置的机器人 QQ 接收消息并按"亚托莉"人设回复。

## 当前完成内容

当前 `main` 对应 v0.4，以下按“核心链路、v0.4 新能力、既有能力、工程化优化”列出已实现内容：

### 核心聊天链路

- NapCat 通过 OneBot v11 反向 WebSocket 接入；支持私聊、群聊、@触发、回复策略、消息拆分和 OneBot action 投递。
- `ConversationTurn` 固定单轮顺序：上下文组装 → Agent/工具调用 → 交付计划；工具调用写入 receipt，失败时禁止模型伪造成功结果。
- 每个会话独立排队和防抖合并，配合健康探测、重连提示、超时和文字降级，避免慢模型或媒体任务造成消息乱序。
- `AtriReplyEngine` 负责人格提示词、原作 lore、记忆上下文、语言护栏、纠错重写、群聊策略和最终回复质量门。

### v0.4 新能力

- **持续认知**：`cognition/` 使用 LangGraph `StateGraph` 建立“理解 → 能力提案”的显式拓扑；`CognitionKernel` 更新目标、情绪、自我经历、当前思考和未解决问题，SQLite/WAL 负责持久化。当前为 shadow mode，不直接产生副作用。
- **回复评测**：`insights/evaluation.py` 通过后台 worker 评估相关性、准确性、完整性、连贯性、忠实性和幻觉风险；支持复用当前聊天模型，也支持独立评测模型。
- **群聊总结**：归档群消息后使用 `jieba`/规则预处理、主题聚类和 LLM 总结，支持最近 24 小时、7 天或自然月的日报/周报/月报，并在 WebUI 展示报告。
- **QQ 空间**：`plugins/qqzone/` 和 `qzone_automation/` 对接本机 Bridge，支持动态读取、人工确认的点赞/评论及可选自动化规则；Cookie 不进入项目配置。
- **音乐工作流**：`music/library.py` 管理完整歌曲目录和 QQ 点歌匹配，`music/session.py` 管理上传、工程阶段、版本和产物；WebUI 支持人声分离、分段、推理、混音和恢复。
- **模块化 WebUI**：原集中页面拆为 `page/body_*`、`page/script_*`，服务端拆为 `server_parts/handler_*`，新增评测、群总结、QQ 空间、用户目录和音乐管理页面。

### v0.3 能力在 v0.4 中继续可用

- RAG 记忆：L1/L2/L3 用户记忆、SQLite FTS5 检索、可选 Ollama `bge-m3` 二次召回和原作 lore 检索。
- LLM 工具箱：时间、联网搜索、网页正文、文档/PDF、表格、图片/OCR、视频关键帧等工具，通过 Function Calling 和统一 Tool Registry 调度。
- 主动陪伴：早安、空闲关怀、群聊冷场插话、用户习惯记录、自迭代纠错和表情包触发。
- 语音与歌声：独立 HTTP 语音服务支持 ASR/TTS、GPT-SoVITS、Edge-TTS、SenseVoice；歌声管线支持人声分离、乐理分段、工程混音和质量门控。

### 工程化与性能优化

- **GPU 资源治理**：跨进程文件锁 + 优先级队列，优先级为聊天 > 用户媒体 > 视觉 > 后台；Ollama 在真实需要时启动，推理结束按配置卸载模型。
- **故障隔离**：评测、群总结、认知影子、QQ 空间和语音均为可选边界；旁路初始化失败不会阻塞基础 QQ 回复。
- **数据隔离**：长期用户记忆、认知状态、评测数据库、QQ 空间自动化数据库和媒体缓存分开存放，均由 `.env`/`data/` 路径控制。
- **可测试性**：新增 cognition、insights、qzone、music、启动链、推理锁和多模态测试；应用层通过 Protocol 降低对具体模型、OneBot 和媒体实现的耦合。
- **开源安全**：`.env.example` 使用占位符，`.gitignore` 排除密钥、聊天历史、SQLite、模型、缓存、音乐素材和 IDE 配置。

## 安装

```powershell
cd "C:\Path\To\AI_ATRI"  # 替换为你的实际路径
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
```

如需接入大模型，编辑 `.env`：

```env
OPENAI_API_KEY=你的_API_Key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
```

不填 `OPENAI_API_KEY` 也能运行，只是会使用本地规则回复。

## 启动机器人服务

```powershell
cd "C:\Path\To\AI_ATRI"  # 替换为你的实际路径
.\.venv\Scripts\Activate.ps1
python -m atri_qq_bot
```

启动后会监听：

```text
ws://127.0.0.1:8765/onebot
```

## NapCat 配置

在 NapCat 中登录你的机器人 QQ，添加一个 OneBot v11 反向 WebSocket 连接：

- 类型：反向 WebSocket / WebSocket Client
- 地址：`ws://127.0.0.1:8765/onebot`
- OneBot 版本：v11

然后用另一个 QQ 给机器人 QQ 发私聊消息，应该能收到亚托莉风格回复。

### WebUI QQ 动态

“QQ动态”页使用独立的 `onebot-qzone` 本机 Bridge 读取 QQ 空间。先按该项目说明完成登录并启动 Bridge，再在本项目 `.env` 设置：

```env
QZONE_BRIDGE_ENABLED=true
QZONE_BRIDGE_URL=http://127.0.0.1:5700
QZONE_BRIDGE_TOKEN=与Bridge一致的AccessToken
```

重启亚托莉后打开 WebUI → QQ动态。也可以进入 WebUI → 测试 → 开发者状态与访问入口，点击“QQ动态 WebUI”直达该页面；下拉列表只显示记忆面板中的人物 QQ，点赞和评论均需在页面人工确认。QQ 空间 Cookie 只应保存在 Bridge 中，不要写入本项目。

## Windows 双端部署（Docker 聊天 + 宿主机语音）

Windows 上推荐的结构：**聊天运行在 Docker**（NapCat + 亚托莉），**语音合成运行在宿主机**（GPT-SoVITS + `atri_voice_service`），两端通过 `host.docker.internal` 互通。

```text
QQ ⇄ NapCat(:6099) ⇄ atri-qq-bot(:8765)
                        ↓
      host.docker.internal:8790 (atri_voice_service)
                        ↓
              :9880 (GPT-SoVITS api_v2)
```

### 前置环境

- Windows + Docker Desktop（需支持 `host.docker.internal` 与目录挂载）。
- Python 3.11（完整安装，含 pip / venv）。
- NVIDIA 显卡驱动；PyTorch 需与显卡型号匹配（RTX 50 系用 cu128，不要用旧的 cu124）。
- 配好项目根 `.env`（`BOT_QQ` / `OWNER_QQ` / 模型 API）。

### 宿主机一次性准备（模型与语音运行时）

1. 下载 GPT-SoVITS 预训练模型与 ATRI 候选音色，放到 `data\models\AI_ATRI\voice\`（`base` + `candidates`）。
2. 建立 ASCII 联接以规避中文路径问题：

   ```powershell
   New-Item -ItemType Junction -Path D:\AtriModels -Target "<LOCAL_MODELS_ROOT>\AI_ATRI"
   ```

   > 脚本默认读取 `<LOCAL_MODELS_ROOT>\AI_ATRI`，可用环境变量 `LOCAL_MODELS_ROOT` 覆盖。

3. 安装 GPT-SoVITS 源码与虚拟环境到 `data\runtime\gpt-sovits\`（`tools/voice/download_gpt_sovits_source.py` + `tools/voice/install_gpt_sovits_runtime.py`）。
4. 安装语音运行时（FunASR / SenseVoice + `atri_voice_service`）：

   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\voice\setup-voice-runtime.ps1
   ```

### 日常启动顺序

先启动宿主机语音，再启动 Docker 聊天：

```powershell
# 语音引擎
powershell -ExecutionPolicy Bypass -File tools\voice\start-gpt-sovits.ps1    # → :9880
powershell -ExecutionPolicy Bypass -File tools\voice\start-voice-service.ps1 # → :8790

# QQ 机器人（聊天）
cd deploy\docker
docker compose up -d --build
```

`.env` 关键语音项：

```env
VOICE_ASR_ENABLED=true
VOICE_TTS_ENABLED=true
VOICE_SERVICE_URL=http://host.docker.internal:8790
VOICE_PROFILE=atri-official-v2pro-curated        # 按你的候选音色档案填写
VOICE_ZH_PROFILE=
```

### NapCat 登录与接线

1. 打开 NapCat WebUI（token 见 `docker logs napcat`）。
2. 机器人 QQ 扫码登录。
3. 反向 WebSocket 指向容器内地址：`ws://atri:8765/onebot`（同一 compose 网络内使用服务名）。
4. 确认亚托莉已连接；管理面板：`http://127.0.0.1:8787`。

### 验收

- GPT-SoVITS：`http://127.0.0.1:9880` 可访问。
- 语音服务：`http://127.0.0.1:8790/health` 返回 `{"ok": true, "ready": true}`。
- WebUI「测试」页：ASR / TTS 试听通过。
- QQ 私聊发「用语音回复我」应收到语音；合成失败会自动降级为文字，不影响主聊天。

### 停止

```powershell
powershell -ExecutionPolicy Bypass -File tools\voice\stop-gpt-sovits.ps1
powershell -ExecutionPolicy Bypass -File tools\voice\stop-voice-service.ps1
cd deploy\docker; docker compose down
```

### 常见踩坑（已实测处理）

| 问题 | 处理 |
|------|------|
| Docker 读不到宿主机合成文件 | 挂载 `E:\...\data\... → /app/data/...`，NapCat 侧用 `base64://` 发送 |
| 全量 `docker build` 太慢 | 项目根加 `.dockerignore`，排除 `models` / `runtime` / `cache` |
| 改代码不想等重建 | `docker cp` 进容器后 `docker restart atri-qq-bot` |
| torchcodec / 音频加载失败 | 语音兼容层回退 `soundfile` |

日常重启只需：GPT-SoVITS → voice service → `docker compose up -d`。

## 配置项

`.env` 中常用配置：

```env
BOT_QQ=YOUR_BOT_QQ
HOST=127.0.0.1
PORT=8765
REPLY_MODE=mention
MESSAGE_SPLIT_MAX_CHARS=44
MESSAGE_SPLIT_MAX_PARTS=4
STICKER_CHANCE=0.24
IDLE_PROACTIVE_ENABLED=true
IDLE_MINUTES=180
IDLE_COOLDOWN_MINUTES=720
OWNER_QQ=
GROUP_CONTEXT_ENABLED=true
GROUP_PROACTIVE_ENABLED=true
GROUP_PROACTIVE_IDLE_MINUTES=90
GROUP_PROACTIVE_COOLDOWN_MINUTES=240
GROUP_PROACTIVE_DAILY_LIMIT=3
MORNING_GREETING_ENABLED=true
MORNING_GREETING_TIME=07:30
MORNING_GREETING_TIMEZONE=Asia/Shanghai
TOOLBOX_ENABLED=true
TOOLBOX_VISION_ENABLED=true
TOOLBOX_VISION_MODEL=qwen2.5vl:3b
TOOLBOX_VIDEO_FRAME_ANALYSIS_ENABLED=true
TOOLBOX_VIDEO_MAX_FRAMES=4
```

### v0.2 新增配置项

```env
# LLM 工具系统：模型可自主调用时间/搜索
LLM_TOOLS_ENABLED=true
LLM_TOOL_MAX_CALLS=2
WEB_SEARCH_ENABLED=true
WEB_SEARCH_TIMEOUT_SECONDS=6
WEB_SEARCH_MAX_RESULTS=5
```

`REPLY_MODE` 可选：

- `private`：只回复私聊。
- `mention`：回复私聊；群聊只在 @机器人或提到"亚托莉/atri"时回复。
- `all`：私聊和群聊所有消息都回复，不建议直接用于大群。

## 电脑关机也能聊

电脑关机后，本机程序不能继续运行。要做到电脑不开机也能和亚托莉聊天，需要把项目部署到一台 24 小时在线的设备上，并让 NapCat/QQ 也在那台设备上保持登录。

云端部署说明在：

```text
deploy/cloud/README.md
```

核心要求：

- 云服务器/NAS/软路由/旧电脑保持在线。
- NapCat 的 OneBot v11 反向 WebSocket 仍然连接 `ws://127.0.0.1:8765/onebot`。
- 模型接口也必须云端可用；如果仍然用本机 Ollama，电脑关机后模型会不可用。

## 每天 7:30 早安

默认已经开启。为了只发给你，建议在 `.env` 里填：

```env
OWNER_QQ=你的QQ号
```

如果不填，亚托莉会发给已经和她私聊过的人。每天只发一次，服务 7:30 附近重启也不会重复刷屏。

## 表情包

模型发送表情包只从 `.env` 的 `STICKER_DIR` 读取。当前配置的来源目录是：

```text
<Pictures>\ATRI\聊天表情
```

推荐按情绪放到这些文件夹：

```text
happy / comfort / tired / proud / confused / shy / food / goodnight / default
```

聊天记录里的图片/表情不会写回来源目录，而是自动保存到当前 BOT_QQ 的 QQ 账号记录目录：

```text
<Documents>\Tencent Files\<BOT_QQ>\ATRI\chat_history
```

可用 `STICKER_CAPTURE_DIR` 覆盖归档目录；模型发送来源仍保持为 `STICKER_DIR`。

默认联网表情缓存：

```text
<项目根目录>\data\stickers\_online_default
```

发送来源：

```text
STICKER_DIR 中的本地表情 > 网页 URL > QQ 自带表情 + emoji
```

自定义触发词编辑：

```text
<项目根目录>\data\stickers\triggers.json
```

例如 `"高性能": "proud"` 表示用户说到"高性能"时，优先从 `proud` 文件夹发一张表情包。

## 回复评测与群聊总结

WebUI 的原“开发”入口已替换为“评测”，内含回复质量看板和群聊总结；开发者状态与
NapCat 访问入口移入“测试”，实时日志保留在评测看板。该功能使用独立 SQLite 和后台
worker，不阻塞 QQ 回复。评测模型直接复用“模型”页面当前启用的聊天模型，切换模型后自动
跟随，无需在评测页面重复填写接口或 Key。安装、评分口径、定时任务与隐私说明见
[docs/insights.md](docs/insights.md)。

## 测试

```powershell
cd "C:\Path\To\AI_ATRI"  # 替换为你的实际路径
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
```

## 开发者支持

完整的服务关系、端口、NapCat WebUI、日志、依赖与故障排查见 [DEVELOPER.md](DEVELOPER.md)。

主运行环境由 [requirements.txt](requirements.txt) 锁定：`httpx` 用于模型/API 请求，`websockets` 用于 OneBot 反向连接，`python-dotenv` 读取配置，`Pillow`/`rapidocr`/`onnxruntime` 处理图像与 OCR，`pypdf` 解析 PDF，`imageio-ffmpeg` 抽取视频帧；`pytest` 仅用于开发回归测试。语音与歌唱使用隔离运行时，不应混装进主 `.venv`。

