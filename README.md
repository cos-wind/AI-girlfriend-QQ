# 亚托莉 QQ 陪伴机器人 · Qbot v0.5

基于 **NapCat / OneBot v11** 的 QQ 机器人。通过 OpenAI 兼容模型接口进行角色对话，支持私聊与群聊、长期记忆、资料阅读、语音交互和本地成品点歌。使用浏览器中的 WebUI 管理模型、账号、回复规则与本地数据。

本仓库发布 Qbot 源码及其配套 WebUI、可选语音服务。桌面客户端、桌宠、游戏界面、软件安装包与 AI_music 工程不在本发行版内。当前 QQ 接入仍使用 NapCat，尚未迁移到 SnowLuma / AstrBot。

## v0.5 更新

| 模块 | 本版内容 |
| --- | --- |
| 固定点歌 | 只扫描 `data/music/` 本层的成品音频。明确请求唱歌后展示歌单，用户选定后通过 QQ 语音发送整首；普通聊天不进入点歌处理。 |
| QQ 登录 | 记录本机登录账号与快速登录选择，保留专用 QQ 配置目录；读取 NapCat 的实际在线状态，登录凭据采用缓存与失败退避。正常在线时复用现有会话，掉线后的登录恢复由 NapCat / QQ 决定。 |
| 可选账号管理 | 支持账号注册、账号视图、独立配置与数据目录，以及跟随 NapCat 登录号。新账号需明确确认，避免误用其他账号的记忆。两个账号开关默认关闭。 |
| 回复控制 | 按私聊、群聊、对象规则与频率决定回复，支持分段发送、输入延迟、群聊上下文和入群欢迎。 |
| 记忆与知识 | 支持结构化记忆、SQLite 存储与 FTS5 检索、可选向量检索，以及聊天资料归档和知识检索。 |
| 工具与多模态 | 支持搜索、网页正文读取、文档与图片解析，配合模型能力提供 OCR、视觉分析和语音识别。 |
| 配套管理 | WebUI 管理模型档案、回复策略、记忆、歌单与服务；CPU 语音识别工作进程可在短时间内复用，降低连续识别开销。 |
| 源码部署 | 提供独立 Qbot 入口与路径模块，移除启动链路对桌面 Core API 和桌面组件安装器的依赖。 |

## 工作流程

```text
QQ 用户
  ↕
NapCat / OneBot v11 反向 WebSocket
  ↕
Qbot：账号校验 → 消息与回复规则 → 对话 / 工具 / 记忆 → QQ 消息发送
  ├─ OpenAI 兼容接口：本地 Ollama 或云端模型
  ├─ WebUI：模型、账号、规则、记忆与歌单管理
  ├─ data/music：选定成品 → QQ 语音
  └─ 可选语音服务：语音识别与语音合成
```

点歌直接读取已存在的歌曲文件，不调用模型生成音乐，也不依赖 AI_music 或语音合成服务。

## 快速开始

### 1. 准备环境

- Python **3.11+**，建议使用 3.11。
- 自行安装并登录 [NapCat](https://github.com/NapNeko/NapCatQQ)。本仓库不分发 QQ 或 NapCat 程序。
- 可访问的 OpenAI 兼容模型接口；本机模型可使用 [Ollama](https://ollama.com/)。

在 PowerShell 中执行：

```powershell
git clone https://github.com/cos-wind/AI-girlfriend-QQ.git
cd AI-girlfriend-QQ
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

项目提供 `uv.lock`。使用 uv 的开发者可运行 `uv sync --locked --extra dev` 安装锁定依赖。

### 2. 填写配置

用文本编辑器打开 `.env`，至少设置：

```dotenv
BOT_QQ=你的机器人QQ号
HOST=127.0.0.1
PORT=8765
OPENAI_BASE_URL=https://你的服务商地址/v1
OPENAI_API_KEY=你的密钥
OPENAI_MODEL=服务商支持的模型名称
```

`BOT_QQ` 必须是 NapCat 当前登录的机器人账号。使用本机 Ollama 时，地址通常为 `http://127.0.0.1:11434/v1`，密钥填写 `ollama`，模型名填写本机已经安装的模型。

按需要设置 `OWNER_QQ` 和回复模式：`private` 仅私聊、`mention` 私聊与群内点名、`smart` 按触发规则回复、`all` 接收全部群消息。完整选项见 [.env.example](.env.example)。

### 3. 连接并启动

在 NapCat 的 OneBot v11 网络配置中添加**反向 WebSocket 客户端**，地址填写：

```text
ws://127.0.0.1:8765/onebot
```

仓库提供 [OneBot 配置示例](napcat-onebot11-config.json)，请在自己的 NapCat 实例中按需配置。然后运行：

```powershell
.\.venv\Scripts\python.exe -m atri_qq_bot
```

保持终端运行，在浏览器打开 **http://127.0.0.1:8787**。首次排查环境可运行 `python tools/check_env.py`。启动器脚本属于 Windows 可选辅助入口；也可自行运行 NapCat，然后使用上面的 Python 命令启动 Qbot。

Linux 使用 `.venv/bin/python`；云端部署参见 [部署说明](deploy/cloud/README.md)。WebUI 和 OneBot 默认绑定本机地址，远程访问请自行配置受控网络连接。

## 点歌：放文件即可

将有使用权限的完整歌曲放到 `data/music/`，文件名就是歌名，例如：

```text
data/music/
├─ 示例歌曲A.mp3
└─ 示例歌曲B.wav
```

支持 WAV、FLAC、MP3、OGG、M4A、AAC、OPUS；只扫描本层文件。也可以通过 WebUI 导入成品。

```text
用户：亚托莉，唱首歌
亚托莉：展示歌单，请回复歌名或序号
用户：第一首
亚托莉：[发送整首 QQ 语音]
```

直接请求“唱《示例歌曲A》”时会先列出歌单并提示确认，回复“确认”再发送。选歌会话有效期为 5 分钟，支持“取消”。普通聊天不会因为提到歌曲就自动回复歌曲未学会。

## 模型、记忆与语音

- **模型档案**：在 WebUI 中保存并启用聊天、视觉等接口。接口地址、模型名、鉴权与供应商一致时才可用；各供应商的额度独立。
- **记忆与账号**：配置和运行数据保存在本机。首次使用建议保持默认单账号设置；需要隔离账号时阅读 [账号管理](docs/accounts.md)。
- **语音**：收发普通文本与成品点歌不要求安装本地语音模型。识别用户语音、实时语音及 TTS 需要额外服务、模型和参考素材，见 [语音部署与素材来源](docs/voice.md)。
- **资料与评测**：搜索、OCR、向量检索等功能受依赖和模型配置影响；向量评测属于可选安装，见 [评测与群聊总结](docs/insights.md)。
- **外部服务**：WebUI 中的 AI_music、QQ 空间 Bridge 等入口需要另外部署对应服务；本发行版不包含这些外部工程。

## 目录

| 位置 | 用途 |
| --- | --- |
| `src/atri_qq_bot/` | OneBot、对话、账号、记忆、工具、点歌与消息发送 |
| `src/atri_webui/` | Qbot 浏览器管理页面及 API |
| `src/atri_shared/` | 共享配置、模型档案、NapCat 登录与服务控制 |
| `src/atri_voice_service/` | 可选本地语音服务 |
| `src/atri_runtime.py` | 源码资源位置与可选用户数据根目录 |
| `docs/prompts/` | 公开角色设定与提示词模板 |
| `tools/`、`deploy/` | 运行辅助、语音部署和服务器部署脚本 |
| `tests/` | Qbot 与配套服务的回归测试 |
| `data/` | 本机数据；发行版仅提供说明与空词典模板 |

## 隐私与开发

实际 `.env`、API Key、QQ 登录凭据、聊天记录、记忆库、数据库、日志、歌曲、参考音频、模型权重与本地运行环境均不随本版上传。测试中的账号使用示例编号。`.gitignore` 默认忽略运行数据，请勿强制加入个人文件。

消息会按启用的功能发给配置的模型或外部工具服务。使用云端 API 前请按自己的需求选择服务商；公开分享日志时应先去除账号、密钥和消息内容。

开发与检查命令见 [DEVELOPER.md](DEVELOPER.md)。本版执行源码编译、隔离导入与自动化回归检查；真实 QQ 登录、模型推理和设备上的语音效果仍需使用者完成配置后实测。

## 项目与支持

- 项目：[cos-wind/AI-girlfriend-QQ](https://github.com/cos-wind/AI-girlfriend-QQ)
- 网站：[yatuoli.com](https://yatuoli.com/)
- 交流群：**1095215340**

欢迎通过 GitHub Issues 提交复现步骤与脱敏日志，通过 Star、使用反馈和代码贡献支持项目。
