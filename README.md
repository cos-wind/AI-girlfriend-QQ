# 亚托莉 QQ 陪伴机器人 — Atri QQ Bot

<p align="center">
  <strong>基于 OneBot/NapCat 协议的 AI 陪伴机器人</strong><br>
  RAG 记忆检索 · Function Calling · 联网搜索 · 语音/歌声 · 工具箱 · 桌宠 · Web 管理面板
</p>

---

## 版本

| 分支 | 版本 | 说明 |
|------|------|------|
| `main` / `v0.4` | **v0.4** (当前) | ✅ 默认分支，内容与 `v0.4` 同步，始终为最新版本 |
| `v0.2` | **v0.2** | 重构为包结构 + LLM Function Calling 工具系统 |
| `v0.1-original` | **v0.1** | 原始扁平文件版本，仅作存档 |

### v0.4 相比 v0.3 新增功能

- **持续认知内核** — 影子模式维护目标、思维承接、情绪与自我经历，不替代正常回复或执行副作用操作。
- **回复评测与群聊总结** — 独立 SQLite 与后台 worker，提供质量评测、群聊归档、主题聚类和定时总结。
- **QQ 空间扩展** — 通过本机 Bridge 接入动态读取、点赞/评论确认和可选自动化，Cookie 不写入本项目。
- **模块化重构** — 记忆、人格、OneBot、工具箱、WebUI 和语音服务进一步拆分，新增音乐、媒体和运行时服务支持。

### v0.3 相比 v0.2 新增功能

- **RAG 记忆检索** — 分层记忆 + 语义召回：
  - `memory_parts/core.py` — L1/L2/L3 分层记忆（强化确认、活跃度衰减、沉睡）
  - `retrieval/` — SQLite FTS5 索引（默认）+ 可选 bge-m3 向量化，`recall_context` 检索注入
  - 后台异步提取，WebUI 可编辑带回写优先级
- **LLM Agent 工具系统** — `llm_tools/`：
  - Function Calling：`get_current_time`、`search_web`（Bing/Google News/arXiv/GitHub + 首条原文 grounding）
  - Agent 协议 (`agent_protocol.py`)：多步工具协商，`web_page_tool` 自动读网页正文
- **语音模块** — 完整 TTS/ASR 管线：
  - `atri_voice_service/` — 独立 HTTP 语音合成服务（GPT-SoVITS / Edge-TTS 双引擎）
  - `atri_qq_bot/voice/` — QQ 端语音决策与发送（6 层决策链）
  - SenseVoice ASR 语音识别，支持热词优化和口音矫正
  - 质量门控：MOS 评分 + 时长校验，低质量自动降级为文字
  - 流式语音回复（SSML），支持说话中被打断
  - 语音训练脚本：GPT-SoVITS v2Pro LoRA 微调管线
- **歌声合成** — `atri_voice_service/singing*` + `tools/voice/`：人声分离、乐理分段、工程混音、质量门、全流程脚本
- **工具箱 (Toolbox)** — 文档/表格/网页/图片/视频材料解析：PDF 抽取、OCR、本地视觉模型识图、视频关键帧分析、表格概览
- **主动规划 v2** — 分层活动检测与多策略空闲关怀，群聊冷场插话
- **WebUI 增强** — 配置、记忆、表情、语音/歌声、模型档案、Minecraft 桥接管理面板
- **架构加固** — 迭代自纠错、OneBot v11 完整实现、桌面宠物启动链（`.venv pythonw` 无终端接管）
- **安全清理** — 所有硬编码 QQ 号和本地路径已替换为占位符/环境变量，适合开源发布

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
