# ATRI QQ动态（MaiBot 插件）

这是一个面向 MaiBot 1.2 / `maibot-plugin-sdk` 2.7+ 的最小可运行实现。它使用
onebot-qzone 作为 QQ 空间 HTTP Bridge，在 MaiBot WebUI 中提供动态读取、点赞、
评论、草稿生成和发布；发布也可切换到 NapCat 原生 `send_qzone_msg`。操作记录保存在
插件私有 SQLite 数据库。

## 组件关系

```text
浏览器 /api/webui/qqzone/*
        │ MaiBot 登录鉴权
        ▼
webui_router.py（MaiBot 主进程）
        │ SDK API RPC
        ▼
plugin.py（隔离插件 Runner） ── SQLite
        │ 本机 HTTP + Bearer Token
        ▼
onebot-qzone ── QQ 空间（读取 / 赞 / 评论）
        └────── NapCat send_qzone_msg（可选发布后端）
```

`maibot-plugin-sdk` 当前没有动态注册 FastAPI 路由的公开能力，所以本插件附带一个
幂等安装脚本，只在 MaiBot 的 `src/webui/routes.py` 挂载一个路由。插件业务代码不
导入 MaiBot `src.*`，仍遵守插件隔离边界。

## 安装

1. 把整个 `qqzone` 目录复制到 MaiBot 的 `plugins/qqzone/`。
2. 安装并运行 [onebot-qzone](https://github.com/Gu-Heping/onebot-qzone)，完成 QQ 登录，
   建议只监听 `127.0.0.1` 并设置 Access Token。
3. 在 MaiBot 根目录执行：

   ```bash
   python plugins/qqzone/install_webui.py .
   ```

4. 重启 MaiBot，在插件管理中启用 `atri.qqzone`，打开插件配置：

   ```toml
   [bridge]
   enabled = true
   base_url = "http://127.0.0.1:5700"
   access_token = "和 onebot-qzone 一致的 Token"
   ```

   若 NapCat 版本已提供 `send_qzone_msg`，可让发布直接走 NapCat：

   ```toml
   post_backend = "napcat"
   napcat_base_url = "http://127.0.0.1:3000"
   napcat_access_token = "NapCat HTTP Token"
   ```

5. 从首页的“QQ 动态”卡片进入，或访问 `/api/webui/qqzone/page`。

卸载 WebUI 路由可执行：

```bash
python plugins/qqzone/install_webui.py . --uninstall
```

安装脚本首次运行会生成 `src/webui/routes.py.before-qqzone.bak`，并使用带标记的最小
补丁，可重复执行。升级 MaiBot 后若上游覆盖了路由文件，重新运行脚本即可。

## 数据与用户来源

- 动态好友资料来自 onebot-qzone 的 `get_friend_list`。
- WebUI 同时读取 MaiBot 人物/记忆面板 `/api/webui/person/list?platform=qq`，按 QQ 号
  与好友资料合并。因此页面中的人物沿用记忆面板，不创建第二套人物数据库。
- 只有 5–20 位纯数字 `user_id` 会作为 QQ 号用于拉取空间。
- 插件数据位于 MaiBot 为该插件分配的 data 目录：`qqzone.sqlite3`。其中包含动态
  元数据缓存、写操作审计、草稿和调度状态，不存储 Access Token。

## 功能与安全配置

`config.toml` 中的重要配置：

| 配置 | 默认值 | 说明 |
|---|---:|---|
| `bridge.enabled` | `false` | 总开关，部署 Bridge 后再启用 |
| `bridge.allow_remote` | `false` | 默认拒绝非回环地址 |
| `bridge.post_backend` | `qzone_bridge` | 可改成 `napcat`，调用 `send_qzone_msg` |
| `safety.allow_llm_like` | `false` | LLM 是否可直接点赞 |
| `safety.allow_llm_comment` | `false` | LLM 是否可直接评论 |
| `safety.allow_llm_post` | `false` | LLM 是否可直接发动态 |
| `safety.daily_post_limit` | `2` | WebUI、Tool、调度共用的每日发布上限 |
| `safety.default_visibility` | `1` | `0` 所有人、`1` 好友、`2` 仅自己 |
| `proactive.enabled` | `false` | 是否允许定时自主生成并直接发布 |
| `proactive.schedule_hours` | `9,18,22` | 每个小时最多尝试一次 |
| `proactive.source_stream_ids` | `[]` | 指定用于生成的 QQ 聊天流；空时取近期 QQ 流 |

WebUI 点赞、评论、发布前都有浏览器确认。LLM 的三项写权限默认关闭，`get_feeds`
始终是只读 Tool。开启 `proactive.enabled` 表示授权定时器跳过人工确认；它仍受最短
间隔、时间槽和每日上限约束。建议先只使用“生成草稿”，观察数日后再开启自动发布。

## LLM Tools

- `get_feeds(user_id="", limit=20)`
- `like_feed(user_id, tid)`
- `comment_feed(user_id, tid, content)`
- `post_feed(content, who_can_see=1)`

Tool 使用动态列表缓存补齐 onebot-qzone 点赞所需的 `appid`、`typeid`、`unikey`、
`curkey`、`abstime`。因此点赞/评论前应先调用 `get_feeds` 或在 WebUI 刷新动态。

## onebot-qzone Action 映射

| 插件操作 | Action |
|---|---|
| 好友列表 | `get_friend_list` |
| 好友动态流 | `get_friend_feeds` |
| 指定用户动态 | `get_emotion_list` |
| 点赞 | `send_like` |
| 评论 | `send_comment` |
| 发布 | `send_msg` |

NapCat 原生发布后端使用 `send_qzone_msg(content, images, ugc_right, target_uins)`；
可见性会映射为 `1=所有人`、`4=好友`、`64=仅自己`。截至本实现对应的 NapCat 版本，
好友空间列表、空间点赞和空间评论仍不属于其完整公开 Action 集，因此这些能力由
onebot-qzone 补齐。NapCat 继续作为 MaiBot 的 QQ 消息协议端，两者使用同一个机器人
QQ 账号。

QQ 空间接口属于非官方协议能力，可能随 QQ 风控或 Bridge 版本发生变化。使用小号、
限制频率、只监听本机，并自行承担账号限制风险。
