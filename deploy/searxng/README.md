# SearXNG 自托管搜索服务

本目录提供一键启动 **SearXNG** 的配置。SearXNG 是一个自托管的元搜索引擎，
聚合 Google / Bing / DuckDuckGo / Wikipedia 等 70+ 源，返回结构化 JSON，
可解决 ATRI 联网搜索在国内 IP 下"Bing 锁中文、DDG 反爬、Google News 英文查不到"的召回难题。

## 为什么需要它

ATRI 当前的搜索工具是"零 API 直连"方案，实测在国内网络下有三个硬伤：

| 源 | 问题 |
|---|---|
| Bing Web RSS | 按来源 IP 强制中文市场，`mkt=en-US` 无效，英文技术术语跑偏成"人民教育出版社" |
| DuckDuckGo | 触发人机验证（"select all squares containing a duck"） |
| Google News | 中文市场下英文术语召回为空，且返回重定向 URL 读不到正文 |

SearXNG 自托管后：
- 返回 `format=json` 结构化结果，解析比 RSS/HTML 稳定
- 可选英文/中文语言，英文技术术语召回正常
- 可启用多个引擎做容错

## 前置条件

1. 安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)
2. 磁盘有约 1GB 空闲空间

## 启动

```bash
# Windows（PowerShell / CMD）
docker compose -f docker-compose.yml up -d

# 或直接用脚本（双击 / 在终端运行）
./start-searxng.bat
```

启动后访问 http://127.0.0.1:8888 确认能看到 SearXNG 搜索页。

## 接入 ATRI

在项目根目录的 `.env` 里加一行（多个实例用英文逗号分隔）：

```
ATRI_SEARXNG_INSTANCES=http://127.0.0.1:8888
```

然后重启后端。`web_search_tool.py` 会优先走 SearXNG JSON，失败再回退到 Bing/Google RSS。

## 常见问题

- **端口冲突**：改 `docker-compose.yml` 里 `SEARXNG_PORT` 的映射（默认 `8888:8080`）。
- **搜索慢**：SearXNG 会并行请求多个引擎，首次可能 3~5 秒，可调 `settings.yml` 里的 `outgoing.request_timeout`。
- **想加代理**：在 `docker-compose.yml` 的 `environment` 里加 `SEARXNG_PROXY=http://你的代理:端口`（若你有海外代理，可让 SearXNG 出网更稳）。
- **停用**：`docker compose down`。
