# 亚托莉 QQ 陪伴机器人

## 小白启动方式

最简单：

1. 像平时一样启动 QQ：`C:\Program Files\Tencent\QQNT\QQ.exe`
2. 后台监听器会在 1 秒内接管启动，拉起可见的 NapCat QQ，同时后台启动 Ollama 和亚托莉服务
3. 如果 QQ 要扫码登录，请扫码一次
4. 用另一个 QQ 给 `3380609082` 发私聊消息测试

停止机器人：

- 平时不用手动停止，关闭 QQ 即可。
- 如果需要彻底停止，可以运行项目里的 `stop-all.bat`。

NapCat 的 OneBot 反向 WebSocket 已经自动配置为：`ws://127.0.0.1:8765/onebot`。不要双击 `run.ps1`，Windows 很容易把它当文本文件打开。

这是一个最小可运行的 NapCat / OneBot v11 反向 WebSocket 机器人，用 QQ `3380609082` 接收消息并按“亚托莉”人设回复。

## 当前完成内容

- 监听 NapCat 反向 WebSocket 事件。
- 默认绑定机器人 QQ：`3380609082`。
- 私聊自动回复；群聊默认仅在 @机器人、提到“亚托莉”或“atri”时回复。
- 支持 OpenAI 兼容接口；没有 API Key 时使用本地人设兜底回复。
- 私聊、群整体、群内用户分别保留聊天记录和对话特征，便于连续聊天和独立适配。
- 群聊会读取群上下文；被 @ 或提到“亚托莉/atri”时按上下文回复。
- 支持群聊低频冷场主动发言，默认冷场 90 分钟后才轻量插一句，单日单群最多 3 次。
- 回复会自动拆成多条短句发送，模拟流式输出，避免长段刷屏。
- 会记录用户聊天习惯，自动调整回复长短、节奏和表情频率。
- 支持自迭代纠错：用户指出错误时会自主判断，合理就认错改正，笼统就认一半并重答，越界或破坏人设的要求会傲娇拒绝。
- 支持本地表情包：按情绪匹配图片，也支持自定义触发词。
- 支持自动归档聊天记录里的图片/表情包，并从本地表情库主动发送。
- 支持手机端直接发送的文档、表格、PDF、图片和视频材料：文档会抽取正文，表格会汇总字段/样例/数值概览，图片会调用本机视觉模型做基础识图和审美评价，视频会在能取得文件时抽取关键帧分析。
- 支持空闲轻量主动关心，默认 3 小时空闲后最多半天提醒一次。
- 支持每天早上 7:30 主动发送元气早安，带防重复和补发窗口。
- 内置亚托莉原作设定摘要和梗库，回复前会做人设校验。
- 已接入桌面原 QQ 图标联动启动：点击原有 `QQ.lnk` 后，后台监听器会接管并恢复 QQ 界面，亚托莉和模型服务在后台启动，不新增桌面图标，不弹终端窗口。

## 安装

```powershell
cd "D:\Codex project\ai-girlfriend-qq"
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
cd "D:\Codex project\ai-girlfriend-qq"
.\.venv\Scripts\Activate.ps1
python -m atri_qq_bot
```

启动后会监听：

```text
ws://127.0.0.1:8765/onebot
```

## NapCat 配置

在 NapCat 中登录 QQ `3380609082`，添加一个 OneBot v11 反向 WebSocket 连接：

- 类型：反向 WebSocket / WebSocket Client
- 地址：`ws://127.0.0.1:8765/onebot`
- OneBot 版本：v11

然后用另一个 QQ 给 `3380609082` 发私聊消息，应该能收到亚托莉风格回复。

## 配置项

`.env` 中常用配置：

```env
BOT_QQ=3380609082
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

`REPLY_MODE` 可选：

- `private`：只回复私聊。
- `mention`：回复私聊；群聊只在 @机器人或提到“亚托莉/atri”时回复。
- `all`：私聊和群聊所有消息都回复，不建议直接用于大群。

## 电脑关机也能聊

电脑关机后，本机程序不能继续运行。要做到电脑不开机也能和亚托莉聊天，需要把项目部署到一台 24 小时在线的设备上，并让 NapCat/QQ 也在那台设备上保持登录。

云端部署说明在：

```text
D:\Codex project\ai-girlfriend-qq\deploy\cloud\README.md
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

把图片放进：

```text
D:\Codex project\ai-girlfriend-qq\data\stickers
```

推荐按情绪放到这些文件夹：

```text
happy / comfort / tired / proud / confused / shy / food / goodnight / default
```

自动保存聊天记录表情包：

```text
D:\Codex project\ai-girlfriend-qq\data\stickers\_chat_history
```

默认联网表情缓存：

```text
D:\Codex project\ai-girlfriend-qq\data\stickers\_online_default
```

发送优先级：

```text
手动添加的本地表情 > 聊天记录归档表情 > 默认联网缓存表情 > 网页 URL > QQ 自带表情 + emoji
```

自定义触发词编辑：

```text
D:\Codex project\ai-girlfriend-qq\data\stickers\triggers.json
```

例如 `"高性能": "proud"` 表示用户说到“高性能”时，优先从 `proud` 文件夹发一张表情包。

## 测试

```powershell
cd "D:\Codex project\ai-girlfriend-qq"
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
```
