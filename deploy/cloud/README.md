# 云端离线运行方案

这里的“离线”指你的电脑可以关机，但亚托莉仍然在线。实现条件是：

- 亚托莉服务运行在一台 24 小时在线的设备上，比如云服务器、NAS、软路由或旧电脑。
- NapCat/QQ 也在同一台在线设备上保持登录。
- 模型接口在云端可访问。电脑关机后，`127.0.0.1:11434` 这种本机 Ollama 地址不会再可用，除非 Ollama 也装在云服务器上。

## 推荐结构

```text
云服务器 / NAS
├─ NapCat QQ，登录 3380609082
├─ 亚托莉服务，监听 ws://127.0.0.1:8765/onebot
└─ 模型接口：云端 Ollama 或 OpenAI 兼容 API
```

不要把 `8765` 端口直接暴露到公网。NapCat 和亚托莉在同一台机器上时，用 `127.0.0.1` 最稳。

## Ubuntu 一键安装服务

把项目复制到服务器后，在项目根目录执行：

```bash
sudo bash deploy/cloud/install-ubuntu.sh
```

然后编辑：

```bash
sudo nano /opt/atri-qq-bot/.env
```

至少检查这些项：

```env
BOT_QQ=3380609082
OWNER_QQ=你的QQ号
OPENAI_BASE_URL=http://127.0.0.1:11434/v1
OPENAI_MODEL=qwen2.5:7b
MORNING_GREETING_TIME=07:30
```

启动亚托莉：

```bash
sudo systemctl start atri-qq-bot
sudo systemctl status atri-qq-bot
```

查看日志：

```bash
sudo journalctl -u atri-qq-bot -f
```

## NapCat 配置

NapCat 的 OneBot v11 反向 WebSocket 地址保持：

```text
ws://127.0.0.1:8765/onebot
```

如果 NapCat 和亚托莉不在同一台机器上，需要用内网、隧道或防火墙白名单连接，不建议直接公网裸奔。

## 每天 7:30 早安

默认开启：

```env
MORNING_GREETING_ENABLED=true
MORNING_GREETING_TIME=07:30
MORNING_GREETING_TIMEZONE=Asia/Shanghai
MORNING_GREETING_CATCHUP_MINUTES=90
```

防重复逻辑：

- 每天只发一次。
- 如果服务 7:30 正好重启，90 分钟内恢复也会补发一次。
- 如果 `OWNER_QQ` 留空，会发给已经和亚托莉私聊过的人；建议正式使用时填你的 QQ。
