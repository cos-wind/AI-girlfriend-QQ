# Qbot v0.5 账号管理

## 先保持单账号运行

默认配置是：

```dotenv
ACCOUNT_SYSTEM_ENABLED=false
ACCOUNT_FOLLOW_NAPCAT=false
```

将 `BOT_QQ` 填为 NapCat 实际登录号即可。没有退出、没有切换且 NapCat 仍然在线时，Qbot 读取已有会话，不应要求重新扫码；QQ / NapCat 本身掉线或会话失效时仍需按框架提示恢复登录。

Windows 辅助启动器使用专用的 `QQ_PROFILE_DIR` 保存 QQ 运行状态。不要把它指向日常 QQ 的 `%APPDATA%/QQ`；也不要删除或公开分享这个目录。已经自行运行 NapCat 的用户可直接运行 Qbot，无需重复启动 QQ。

## 启用账号隔离

需要管理多个账号时，在 `.env` 中设置并重启：

```dotenv
ACCOUNT_SYSTEM_ENABLED=true
ACCOUNT_FOLLOW_NAPCAT=true
ACCOUNTS_DB_PATH=data/accounts/index.sqlite3
```

在 WebUI 的账号管理中登记并确认新账号。跟随模式根据 NapCat 的 `get_login_info` 确定实际登录号；未确认的新账号会阻止消息进入其他账号的数据区。关闭跟随模式时，配置中的 `BOT_QQ` 仍承担账号匹配约束。

账号视图用于查看、编辑对应账号的配置；实际处理消息的账号由运行状态决定。切换查看对象不等于已经切换 QQ 登录。切换后先检查 WebUI 显示的实际在线账号与数据范围，再发送测试消息。

## 数据位置

默认账号使用项目原有的 `data/memory/`、`data/webui/` 等位置。新增账号在 `data/accounts/qq-<账号>/` 下保存对应记忆、配置、认知与评测状态；共享资源按模块约定使用。账号开关不会自动迁移或合并个人历史数据。

登录历史和快速登录选择保存在本机运行数据中，不随源码发布。停用账号或备份前请先停止相应服务；勿将注册表、QQ 配置、凭据缓存及账号目录上传 GitHub。
