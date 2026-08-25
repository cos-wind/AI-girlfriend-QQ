# ATRI 回复评测与群聊总结

该模块是 OneBot 回复链路旁边的独立旁路。QQ 回复发送完成后只投递一个
`EvaluationSample`；DeepSeek 请求、SentenceTransformers 推理和 SQLite 写入都由后台
worker 完成。模块故障只写日志，不会阻止 ATRI 回复。

## 安装

核心功能不强制安装重型向量依赖。需要语义相似度和向量话题聚类时执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-insights.txt
# 开发安装也可使用：pip install -e ".[insights]"
```

首次使用默认模型时，SentenceTransformers 会下载
`paraphrase-multilingual-MiniLM-L12-v2`。离线部署请预先缓存模型并设置
`INSIGHTS_EMBEDDING_LOCAL_ONLY=true`。若依赖或模型不可用，回复评测会保留 DeepSeek
分数，群聊话题会自动退化为关键词聚类。

## 评测模型配置

评测默认直接使用 WebUI“模型”页面当前启用的聊天模型，因此只需在那里配置接口和
API Key。下面的环境变量仅用于关闭跟随模式时的旧版兼容配置：

```env
EVALUATION_API_KEY=你的DeepSeek密钥
EVALUATION_BASE_URL=https://api.deepseek.com/v1
EVALUATION_MODEL=deepseek-chat
```

如果当前聊天模型是本机 Ollama，就会自动使用本机模型；如果是 DeepSeek，就会自动使用
当前 DeepSeek 配置。无需在评测面板再次填写 Key。

## 评测模型来源与使用方式

ATRI 每次完成正常 QQ 回复后，会把问题、回复和本轮检索上下文投递到后台队列。写入
SQLite、调用评测模型和 SentenceTransformers 推理都在旁路 worker 中执行，不等待评测
结果，因此不会增加 QQ 回复延迟。

评测模型不在“评测”面板重复配置，而是直接复用 WebUI“模型”页面当前启用的聊天模型：

1. 进入“模型”页面，在“模型档案”中保存并启用一个聊天模型（Ollama、DeepSeek 或其他
   OpenAI 兼容接口）。
2. 评测旁路自动读取该模型的接口、模型名和密钥；无需再次填写。
3. 进入“评测 → 评测看板”查看异步结果。切换模型并启用后，评测模型会随配置热加载。

如果评测失败，先在“模型”页面点击“测试当前聊天模型”确认接口可用，再在评测看板点击
“批量重试失败”。

如果当前 `OPENAI_BASE_URL` 本身就是 DeepSeek，旁路可以安全复用
`OPENAI_API_KEY`；否则绝不会把聊天模型密钥发到 DeepSeek。完整配置见
[.env.example](../.env.example)。修改定时总结配置后 WebUI 会热加载；切换数据库路径需要
重启 ATRI。

## 评分口径

所有维度使用 0～5 分，分数越高越好：

- `relevancy`：DeepSeek 评分与语义相似度加权，语义默认只占 15%。
- `accuracy`：检查事实、数字、概念与因果；无参考答案时会标记证据限制。
- `completeness`：覆盖用户问题中所有明确要求。
- `coherence`：逻辑、结构、前后一致性。
- `faithfulness`：把回答拆成声明，并计算可由检索上下文支持的比例；无上下文为 N/A。
- `hallucination`：高分表示未发现无依据编造。

总体分不再使用简单算术平均，而是使用加权几何均值：准确性、忠实度和无幻觉程度
权重更高，低分会对总体质量产生更明显的惩罚，避免多个表达类高分掩盖事实性风险。
趋势图同时展示质量指数、P25–P75 分布带、低分率、波动值和较前日变化，并采用局部
Y 轴刻度；因此 4.1→4.3 这类小幅但持续的退化也能被看见。

可用 `EVALUATION_DIMENSIONS` 单独启用或禁用维度。数据库包含原问题、回复和本轮检索
上下文，因此 `data/insights/` 已加入 `.gitignore`，备份和分享前请按聊天隐私处理。

## 群聊总结

ATRI 只总结自身启动后收到并归档的群消息。WebUI 的“评测 → 群聊总结”支持选择群聊、
每日总结/周报/月度总结；任务创建后在后台执行，日报按当前时刻向前 24 小时、周报向前
7 天、月报严格从本月 1 日到当前时刻，不需要用户填写开始时间和结束时间。自动总结默认
关闭，可配置执行时间和周期，使用机器本地时区。

WebUI 对应的请求格式为 `{"group_id":"群号","period_type":"daily|weekly|monthly"}`；服务会在任务创建时自动计算周期窗口。

处理顺序：

1. 归档消息并计算成员排行、关键词、周期活跃分布（每日 24 小时、周报 Monday–Sunday、月报按周）、提问/链接/待办信号。
2. 根据消息量、消息速率和参与人数选择低活跃、一般活跃、活跃、高活跃四档，动态调整语义块大小、话题数量和输出长度。
3. 将各话题代表消息、时间线和重点证据交给当前聊天模型生成亚托莉口吻的结构化摘要。
4. 当前聊天模型不可用时仍保存确定性的关键词聚类报告。

报告可在 WebUI 查看，并导出 Markdown、JSON 或“图文报告”。图文报告是自包含 HTML，
按亚托莉风格统一展示“群聊总览和基本信息/周期活跃轨迹”“今日/本周/本月话题 Topics”“群友画像 · 活跃成员”三个核心区块；
话题卡会包含标题、参与者、内容总结和亚托莉的观点，成员卡会包含基于发言数据的简短评价；
打开后点击“打印 / 保存 PDF”即可保存为 PDF，也可以使用浏览器截图保存为 PNG。

群聊选择器和记忆面板会从 NapCat 的 `get_group_list` 同步群名，并缓存到 insights SQLite；
NapCat 暂时离线或旧数据没有群名时，界面回退显示“群 + 群号”，不会影响总结和记忆功能。

## SQLite 表

- `evaluations` / `evaluation_scores`：任务状态、总分和可插拔维度分。
- `group_messages`：收到的群消息（`message_key` 去重）。
- `group_summaries`：手动/定时任务、结构化数据和报告正文。

数据库启用 WAL、外键和 busy timeout，WebUI 线程与 asyncio worker 各用短连接。
