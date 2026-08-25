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

## v0.4 版本说明

v0.4 的重点不是简单增加模型接口，而是把 ATRI 从“能聊天的 QQ Bot”推进为具备持续状态、质量反馈和可扩展外围能力的陪伴系统。所有本地状态默认留在 `data/`，通过 `.env` 配置，公开仓库只保存代码、文档和示例配置。

### 1. 持续认知内核

- `src/atri_qq_bot/cognition/` 提供目标、情绪、自我经历和上下文承接的结构化状态。
- 默认使用影子模式：认知过程可以观察和更新状态，但不替代正常回复，不直接发送 QQ 消息，也不执行副作用工具。
- 状态写入独立 SQLite；路径由 `COGNITION_STATE_PATH` 配置，运行数据不会进入 Git。

### 2. 回复评测与群聊总结

- `src/atri_qq_bot/insights/` 负责回复质量评测、群消息归档、主题聚类和总结生成。
- 评测维度覆盖相关性、准确性、完整性、连贯性、忠实性与幻觉风险，并支持语义相似度辅助评分。
- 群聊总结支持按日、周、月生成，独立后台 worker 不阻塞 QQ 回复；WebUI 提供评测趋势、总结和报告查看入口。
- 相关安装、配置、隐私边界见 [`docs/insights.md`](docs/insights.md)。

### 3. QQ 空间扩展

- `plugins/qqzone/` 提供可选的 QQ 空间插件；`src/atri_webui/qzone_automation/` 提供人工确认和自动化规则管理。
- 通过本机 OneBot Bridge 读取动态、执行点赞/评论等操作；默认关闭，必须显式启用。
- QQ 空间 Cookie 只应保存在 Bridge 中，不能写入本项目 `.env`、数据库或 Git 历史。

### 4. 模块化架构升级

- 记忆、人格、OneBot 服务端、工具箱和 WebUI 拆分为可独立测试的子模块。
- 新增 `music/` 音乐会话、`runtime/` 运行时服务、`server_parts/` 事件与投递处理器，以及模块化 WebUI 页面。
- 旧入口和重复启动链被清理，统一由桌宠/启动脚本负责启动，降低依赖重复安装和多进程冲突。

### 5. 多模态、语音与歌声能力延续并增强

- 保留 v0.3 的 RAG 记忆、联网搜索、Function Calling、文档/PDF/OCR/图片/视频工具箱。
- 语音服务继续独立运行，支持 ASR、TTS、GPT-SoVITS、Edge-TTS 与质量降级；歌声工程支持人声分离、乐理分段、混音和质量检查。
- `tools/voice/` 收纳训练、分析、推理和运行时脚本，避免把重型语音依赖混入主聊天环境。

### 6. 开源发布安全

- `.env.example` 只包含占位符和本地回环地址；真实 API Key、QQ 号、Cookie 不应提交。
- `.gitignore` 排除 `.env`、SQLite、聊天历史、缓存、模型、音乐素材和本机 IDE 配置。
- 文档中的用户目录、模型目录和媒体目录使用通用占位符，部署时按本机环境填写。

### v0.3 基线

v0.3 是 v0.4 的能力基础，首次形成了 RAG 记忆检索、LLM Agent 工具链、OneBot/NapCat 接入、语音/歌声服务、材料工具箱、主动关怀和 WebUI 管理面板。v0.4 在此基础上增加持续认知、质量评测、群聊总结、QQ 空间扩展和更细的模块边界。

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

- 监听 NapCat 反向 WebSocket 事件。
- 默认绑定机器人 QQ：`.env` 中 `BOT_QQ` 配置。
- 私聊自动回复；群聊默认仅在 @机器人、提到"亚托莉"或"atri"时回复。
- 支持 OpenAI 兼容接口；没有 API Key 时使用本地人设兜底回复。
- 私聊、群整体、群内用户分别保留聊天记录和对话特征，便于连续聊天和独立适配。
- 群聊会读取群上下文；被 @ 或提到"亚托莉/atri"时按上下文回复。
- 支持群聊低频冷场主动发言，默认冷场 90 分钟后才轻量插一句，单日单群最多 3 次。
- 回复会自动拆成多条短句发送，模拟流式输出，避免长段刷屏。
- 会记录用户聊天习惯，自动调整回复长短、节奏和表情频率。
- 记忆分层沉淀：重要信息强化确认后进入长期记忆，长期无互动的记忆自动降权沉睡；支持语义检索召回历史相关记忆。
- 支持自迭代纠错：用户指出错误时会自主判断，合理就认错改正，笼统就认一半并重答，越界或破坏人设的要求会傲娇拒绝。
- 支持本地表情包：按情绪匹配图片，也支持自定义触发词。
- 支持自动归档聊天记录里的图片/表情包，并从本地表情库主动发送。
- 支持手机端直接发送的文档、表格、PDF、图片和视频材料：文档会抽取正文，表格会汇总字段/样例/数值概览，图片会调用本机视觉模型做基础识图和审美评价，视频会在能取得文件时抽取关键帧分析。
- 支持空闲轻量主动关心，默认 3 小时空闲后最多半天提醒一次。
- 支持每天早上 7:30 主动发送元气早安，带防重复和补发窗口。
- 内置亚托莉原作设定摘要和梗库，回复前会做人设校验。
- 已接入桌面原 QQ 图标联动启动：点击原有 `QQ.lnk` 后，后台监听器会接管并恢复 QQ 界面，亚托莉和模型服务在后台启动，不新增桌面图标，不弹终端窗口。
- 🔧 **LLM Agent 工具系统**：模型可自主调用时间查询、联网搜索（自动读原文）、网页正文抓取，不需要时不产生任何 token 开销。
- 🧠 **语音与歌声**：可选语音回复（TTS/ASR）、歌声合成（人声分离 + 工程混音），由独立语音服务承载。

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

