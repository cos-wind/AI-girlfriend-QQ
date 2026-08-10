# 语音模块

语音模块由 QQ 主进程和独立的本地语音服务组成。默认关闭；服务不可用、模型未就绪、合成失败或 QQ 发送失败时，主进程回退到文字，不影响聊天、WebUI 和桌宠。

## 数据流

1. 用户语音先由 NapCat `get_record` 转为 WAV。
2. 独立服务把输入统一为 16kHz 单声道 PCM，使用 FSMN-VAD 分段，再由 SenseVoiceSmall 识别文本和基础情绪。
3. 文本进入现有聊天模型。启用 TTS 后，模型可自主调用 `speak_as_atri`。
4. 用户明确要求语音或唱歌但模型漏调工具时，窄范围交付保护器会使用模型最终回复补建语音请求。
5. 独立服务先检索完整原声，再调用 GPT-SoVITS；合成结果可由 SenseVoice 回读检查漏字，NapCat 最终以 `record` 消息发送。

## 模块边界

语音服务按用途分成两条互不替代的管线，`SpeechApplication` 只负责 HTTP
用例编排，不再承载具体推理流程：

```text
SpeechApplication
├─ ConversationSpeechPipeline
│  ├─ 完整日常原声匹配
│  ├─ GPT-SoVITS 合成
│  └─ ASR 回读、重试、中性补救与拒发
└─ SingingService
   ├─ 完整歌声素材匹配
   └─ SingingJobManager
      └─ 人声分离、SVC 转换、混音与歌声质量检查
```

`ConversationSpeechPipeline` 只接受 `mode=speech`，目标是低延迟、清楚和稳定；
`SingingService` 只接受 `mode=singing`，允许较长耗时并通过独立任务报告进度。
两者共享语音档案和显存租约管理，但不共享质量规则、重试状态或输出缓存。
唱歌引擎未配置、任务失败或被取消时，不能影响普通 TTS、ASR 和文字聊天。

兼容接口 `POST /v1/synthesize` 保持不变，并按 `mode` 分流。生成式唱歌继续使用
`/v1/singing/jobs` 异步接口，避免长任务阻塞日常回复。

ASR 属于输入前处理，不是 LLM 工具。模型在识别之前无法理解语音，因此不能自行决定是否识别。普通聊天是否使用语音仍由模型判断；程序级保护器只覆盖“用语音回复”“读出来”“唱两句”等直接要求及其否定形式，不替代通用意图理解。

## 原声素材与质量门

语音服务递归扫描 `C:\Users\YOUR_NAME\Music\ATRI训练音频素材`，每 60 秒自动刷新。标准语料从 `.speaker.list` 读取逐字台词；零散音频使用文件名作为初始台词。只有规范化台词完全相同或相似度至少 0.94 时才直接发送完整原声，原文件保持只读，发送使用 `data\voice\cache\original-clips` 中的缓存副本。

`手搓音频素材` 是日常回复的优先原声层。同一台词存在多个素材时优先使用该
目录；对于“早上好呀，主人”这类只增加少量称呼或语气词的回复，也允许匹配
“早上好”素材。过短台词不会凭关键词替换长回复，避免“有的”“疼”等素材
误命中不相关语境。WebUI 关闭“优先完整原声”后才会跳过这一层。

普通 TTS 可在发送前由 SenseVoice 回读。回读错误率超过 WebUI 阈值时，服务使用不同 seed 重试；全部候选仍不合格时抛出可控错误，QQ 主进程回退文字。WebUI 可独立关闭原声匹配、质量门或调整错误率和重试次数。

质量阈值首先作为严格发送上限。主档案未通过时切换中文救援档案；救援档案
完成全部重试后，只允许长度至少 8 个发音单位、内容长度完整且错误率不超过
20% 的最优候选通过，并标记 `best_effort=true`。短句、跨语言、漏读和严重
失真不放宽。失败响应仍携带最佳候选的回读文本、错误率、尝试次数和阈值，
QQ 侧将这些字段写入 `logs/voice-events.log`。

日常 TTS 使用顺序推理并关闭分桶，短句不切分，长句仅按标点顺序切分。这样可
避免短句在并行语义采样中偶发生成几十秒拖音。后处理还会按文本发音单位检查
总时长；异常拖长即使能被 ASR 识别，也不能通过质量门。

QQ 日常语音在进入 TTS 前按句号、问号和逗号切成不超过
`VOICE_SEGMENT_MAX_CHARS` 个发音单位的语义段，默认 34。每段合成完成后立即
发送，不等待全文完成；单段质量不合格时仅把该段改为文字并继续后续语音，
服务不可用时才停止后续合成并一次发送剩余文字。

中文回读同时计算汉字错误率和带声调拼音错误率。同音字（例如“再议/在意”）
不会因为 ASR 无法区分汉字而误拒；跨语言和真实漏字仍按错误处理。主档案中文
回读失败时可使用 `VOICE_ZH_RESCUE_PROFILE` 指定的中文档案再合成一次，默认
为 `atri-official-v2pro-curated-gpt-e6`。

常见同义短句可直接命中手搓原声，例如“早安”复用“早上好”原声。角色主档案
和中文救援档案都失败后，服务会对 `手搓音频素材` 做一次受限的语境匹配；
只有问候、告别、疼痛、隐私、高性能等明确语义达到安全分数才发送，并标记
`source=original_context_fallback`。没有合适原声时回退文字，不会调用 Windows
系统女声，也不会用不相关原声冒充当前回复。

送入 TTS 的文本保留“嗯”“嘿嘿”“好呀”“高性能”等角色口语词，但会删除
舞台动作，并把波浪号、连续省略号和长破折号转换成正常短停顿。角色习惯由
模型回复内容表达，不通过夸张拉伸音频实现。

歌唱使用独立 `OriginalSingingProvider`，只检索素材根目录下名称包含“歌唱 / 唱歌 / singing / song / vocal”的完整歌声，绝不把普通 TTS 朗读伪装成唱歌。第一阶段把以完整歌词命名的歌声放到 `ATRI训练音频素材\歌唱`；未命中时安全回退文字。任意歌曲的歌声转换将在独立 SVC 引擎阶段接入。

生成式唱歌现已使用独立的异步任务链路，不会占住 QQ 的普通回复请求。服务按固定清单执行“试听截取、人声分离、Seed-VC 44.1k/F0 歌声转换、伴奏混合、WAV 质量检查”，支持查询进度和取消。管线命令只来自管理员保存的 `data\voice\singing-pipeline.json`，聊天文本不能传入可执行命令。

```text
POST /v1/singing/jobs
GET  /v1/singing/jobs/{job_id}
POST /v1/singing/jobs/{job_id}/cancel
```

请求至少包含歌曲名、歌曲源音频和语音档案。默认只处理前 15 秒用于 A/B 试听，输出通过时写入按源文件、参考音频、模型清单和参数寻址的缓存。同一输入再次测试不会重复推理。

```json
{
  "text": "测试歌曲",
  "source_audio_path": "D:\\Music\\song.wav",
  "profile": "atri-official-v2pro-curated",
  "language": "zh",
  "preview_seconds": 15,
  "pitch_shift": 0
}
```

实验运行时与主语音运行时隔离。安装 Seed-VC 和人声分离器并生成管线清单：

```powershell
powershell -ExecutionPolicy Bypass -File tools\voice\setup-seed-vc-singing.ps1
```

模型和两个独立 Python 环境默认写入 `D:\本地大模型\models\AI_ATRI\voice\singing` 的 ASCII 联接路径 `D:\AtriModels\voice\singing`。Seed-VC 使用 44.1k F0 模型、FP16 和 35 个扩散步；RTX 4060 8GB 上按阶段串行运行，不与 ASR/TTS 并发抢显存。

默认分离器使用 `UVR-MDX-NET-Inst_HQ_4.onnx`，安装脚本会校验文件长度，防止中断下载被当成可用模型。BS-Roformer 可作为后续更高质量但更慢、更占显存的可选档案，不能直接用未下载完整的权重替换默认模型。

## 识别质量

WebUI“语音”页提供角色名与专有词纠错。格式为每行 `正确词 = 常见误识别1, 常见误识别2`，保存后由语音服务按文件更新时间自动重载，无需重启。纠错只替换明确列出的别名，不做整句语言模型改写。

当前固定六条中英日合成样本的初筛结果如下。该结果只用于候选筛选，真实麦克风、环境噪声和不同说话人的验收仍应在 WebUI“测试”页完成。

| 引擎 | 平均字符错误率 | 热启动平均耗时 | 结论 |
| --- | ---: | ---: | --- |
| SenseVoiceSmall | 16.8% | 0.30 秒 | 默认主引擎 |
| Fun-ASR-Nano-2512 | 23.6% | 0.81 秒 | 保留离线候选，不常驻 |
| faster-whisper large-v3-turbo | 44.9% | 0.50 秒 | 角色英语声线误判明显，不默认启用 |

基准清单位于 `data\voice\asr-benchmark.json`，报告位于 `data\runtime\asr-benchmark-*.json`。候选运行时与在线语音运行时隔离，不会覆盖 SenseVoice 的依赖。

TTS 档案使用统一的九条中英日、情绪和句型基准进行横向比较：

```powershell
$env:PYTHONPATH="src"
python tools\voice\benchmark_speech_profiles.py
```

报告写入 `data\runtime\speech-profile-benchmark-*.json`，包含成功率、耗时和 ASR 回读错误率，并保留每条 WAV 路径供音色相似度、自然度、情绪贴合度和发音的 1～5 分盲听。自动回读只能发现漏字，不能代替角色音色盲听。

## 安装与启动

```powershell
powershell -ExecutionPolicy Bypass -File tools\voice\setup-voice-runtime.ps1
powershell -ExecutionPolicy Bypass -File tools\voice\start-gpt-sovits.ps1
powershell -ExecutionPolicy Bypass -File tools\voice\start-voice-service.ps1
```

语音代码固定在 `src\atri_voice_service`。独立 Python 运行时默认位于项目的 `data\runtime\voice-runtime`，由 `.gitignore` 排除，不会污染项目主虚拟环境。

本项目使用的语音模型统一存放在 `D:\本地大模型\models\AI_ATRI\voice`。SenseVoice 首次使用时下载到其中的 `modelscope` 子目录，后续 GPT-SoVITS 权重也放在该项目专属目录中。

安装脚本会创建 `D:\AtriModels` 目录联接指向 `D:\本地大模型\models\AI_ATRI`。模型的真实位置不变；ASCII 别名仅用于兼容 Windows 下无法直接打开中文模型路径的 SentencePiece 原生库。

旧版运行时目录只作为启动兼容回退，不再接收新模型。确认新运行时安装完成后可以单独清理旧目录。

## 角色音色

WebUI 的“语音”页面保存 GPT-SoVITS 地址、参考音频及对应原文。参考音频必须是有权使用的单人清晰语音，且原文与音频逐字一致。没有合法参考音频时，档案保持“未就绪”，不会伪装成亚托莉音色。

GPT-SoVITS 服务默认地址为 `http://127.0.0.1:9880/tts`。候选档案彼此独立且可回退：`atri-2dipw`、`atri-voidshine`、`atri-user-reference` 和由 1765 条精选语料训练的 `atri-official-v2pro-curated`。推理只运行固定提交的官方 GPT-SoVITS 源码，不运行候选仓库附带脚本。

`atri-2dipw` 会按 `gentle/happy/shy/sad/serious/surprised` 选择对应的原声参考，并使用参考 WAV 的文件名作为逐字匹配的日语提示文本。`intensity` 会在保守范围内调整语速、temperature 和 top-p；强度为 0 时语速保持 1.0。没有合适参考的情绪继续使用中性参考，不会硬套错误台词。

当请求语言为 `auto` 时，服务按假名、汉字和拉丁字母依次判断日语、中文和英文，不再一律回退为中文。混合语言长句仍建议在 WebUI“测试”页显式选择主语言。

WebUI“语音”页的发音词典格式为 `原文 = 中文读法 | English pronunciation | 日本語の読み方`。它适合固定角色名和缩写，不会训练或改变模型音素能力。保存后按文件更新时间热加载，无需重启。

GPT-SoVITS 使用按语言固定的推理 seed，避免同一句话偶尔出现完全不同的读音。日常语音使用经过拖音 A/B 测试的保守采样参数：`top_k=5`、`top_p=0.76`、`temperature=0.58`、`repetition_penalty=1.3`。短句不切分，长句才按标点切分，并关闭并行推理和分桶。情绪强度只在保守范围调整语速。返回音频会保留约 200ms 起音和 200ms 收尾，裁掉更长的首尾空白；有效语音响度目标约为 -22dBFS，增益最多 +6dB，峰值上限 -1.5dBFS。后处理或文本相关时长检查失败时拒绝该候选，并进入显式重试或错误回退，不发送未经检查的原 WAV。

当前 2DIPW 权重以日语角色数据为主。英文固定测试句可稳定逐字回听；中文仍可能出现近音字，发音词典不能彻底修复跨语言模型上限。中文质量应继续与 `atri-voidshine` 做 A/B 实听后再决定默认档案。

`atri-official-v2pro-curated` 保持为三语默认档案。它使用精选 SoVITS e1
和通用 GPT 权重，在固定中、英、日样例上的平均回读错误率为 `3.89%`。
该档案只使用与微调语料匹配的单一参考音频；情绪由保守的语速、停顿和
采样参数表达，避免混用其他模型参考音频造成长静音、重复和漏字。
`atri-official-v2pro-curated-gpt-e6` 是 WebUI 中可切换的中日语实验档案；
中文回读错误率为 `0%`、日文为 `2.27%`，但英文为 `32.22%`，因此不设为
三语默认。完整报告位于
`D:\AtriModels\voice\training\atri-official-v2pro-curated\benchmark\gpt-candidates\benchmark.json`。

语音档案可按目标语言配置不同参考音频及提示文本。`atri-user-reference` 使用用户提供的亚托莉原声：日语使用两段清晰原声组成的短参考，中文和英文使用单段参考。7 段、约 14 秒的可标注素材已完成两轮 SoVITS 隔离微调，但候选出现过拟合和发音损伤，因此只保留在实验目录，不作为在线权重。

候选 A 使用 CC-BY-NC-SA-4.0 及仓库补充限制；候选 B 使用 AGPL-3.0 及个人/研究用途声明。它们适合本地个人试听，不应在未重新核对许可时用于商业发布。

确认 WebUI 中“独立服务”“语音识别”“角色音色”“原声素材库”和“语音质量门”均就绪后，再启用“识别用户语音”和“允许模型自主发语音”。

## 第一阶段验收

1. 打开 `http://127.0.0.1:8787`，进入“测试”，点击“刷新状态”。服务应显示已连接，两套候选下拉框不应带“未就绪”。
2. 在“语音识别测试”选择自动检测，点击“开始说话”，说完后点击“停止并识别”。也可以上传音频文件；中文、英文、日文均应返回文本和检测语言。
3. 服务启动后会在后台预热 SenseVoice。为避免 8GB 显存同时驻留 GPT-SoVITS 和 ASR 导致原生进程退出，当前启动脚本默认让 SenseVoice 在 CPU 运行；GPT-SoVITS 继续使用 GPU。状态显示“模型正在预热”时可以等待完成，页面会持续显示识别或合成的已用时间。
4. 在“语音合成测试”依次选择中文、English、日本語，点击“生成 A/B 试听”。每种语言应生成两条可播放 WAV，且页面显示各自耗时。
5. 使用同一句日语先比较角色相似度，再比较中文和英文的清晰度。不要只用一条中文试听决定最终档案。
6. 调整“情绪”和“情绪强度”，分别试听中性、开心、难过和害羞。同一模型的情绪参考会变化，强度只做有限语速和采样调整，不应产生夸张变速。
7. 在“语音”页面查看原声素材条数和最近质量状态；用“早上好”等完整素材台词试听时应显示“完整原声”，普通新句子应显示“模型合成”和回读错误率。
8. 私聊发送“用语音回复我”，即使模型只生成文字也必须收到 QQ 语音；发送“不要发语音”必须继续收到文字。
9. 把完整歌声放入 `ATRI训练音频素材\歌唱`，文件名使用完整歌词；“表达方式”选择“歌唱素材”后应命中原声。无匹配素材时必须明确失败，不能朗读歌词。
10. 选定候选后保存当前角色档案；旧档案和权重不会被覆盖，可随时切回。
11. 停止 GPT-SoVITS 后发送普通文字消息，QQ 应继续收到文字回复；需要语音的消息合成失败时也不能影响聊天主流程。

停止独立引擎：

```powershell
powershell -ExecutionPolicy Bypass -File tools\voice\stop-gpt-sovits.ps1
powershell -ExecutionPolicy Bypass -File tools\voice\stop-voice-service.ps1
```
