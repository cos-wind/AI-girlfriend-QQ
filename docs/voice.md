# Qbot v0.5 语音部署与素材来源

## 哪些功能需要语音服务

文本聊天和 `data/music/` 成品点歌可以先独立使用。语音识别（ASR）、文本转语音（TTS）和语音通话另需安装运行依赖、模型并配置端点。发行版不带权重、参考音频、训练语料或个人音色档案。

Qbot 通过 `VOICE_SERVICE_URL` 访问兼容的 HTTP 服务，默认是 `http://127.0.0.1:8790`。配套源码入口为 `python -m atri_voice_service.server`；默认 ASR 使用 SenseVoice，TTS 使用 GPT-SoVITS，需要按硬件安装匹配的 PyTorch 等依赖。

## Windows 本地部署

先完成 README 中的 Qbot 环境和模型配置，再按需准备语音环境：

```powershell
# ASR：建立独立语音环境并安装依赖，默认需要兼容的 NVIDIA CUDA 环境
powershell -ExecutionPolicy Bypass -File tools/voice/setup-voice-runtime.ps1

# GPT-SoVITS：下载固定版本源码，再安装其运行依赖及基础模型
.\.venv\Scripts\python.exe tools/voice/download_gpt_sovits_source.py
.\.venv\Scripts\python.exe tools/voice/install_gpt_sovits_runtime.py
```

这些命令会从公开上游下载依赖和模型，体积较大。CPU 用户应按上游文档安装 CPU 版依赖并设置 `ATRI_ASR_DEVICE=cpu`；默认 CUDA 配置不可直接用于所有设备。

`LOCAL_MODELS_ROOT` 指定共享模型根目录，项目模型位于其 `AI_ATRI/voice/` 下；未设置时采用用户目录下的 `.ollama/models/`。Windows 脚本默认建立项目 `models/` 访问路径，也可通过 `ASCII_ATRI_MODELS_ROOT` 指定仅含 ASCII 字符的路径。请在部署前统一这些目录，勿依赖其他电脑的绝对路径。

准备好模型和 `data/voice/profiles/` 中的音色档案后，用 WebUI 服务开关或对应 `start-voice-service.ps1` / `start-gpt-sovits.ps1` 启动。不同音色须配置真实的 GPT / SoVITS 权重路径、参考音频和参考文本；仅安装基础模型不会自动得到可用的亚托莉音色。

ASR 热词和 TTS 发音词典位于 `data/voice/`。本版提供空词典模板，按需编辑即可。服务端 `/health` 用于检查就绪状态；识别、合成失败时先检查服务日志、模型路径、端点和显存。

## 公开来源

| 类型 | 来源 | 用途 |
| --- | --- | --- |
| ASR | [FunAudioLLM / SenseVoice](https://github.com/FunAudioLLM/SenseVoice) | 语音识别模型与说明 |
| TTS | [RVC-Boss / GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) | 语音合成框架与部署说明 |
| 基础权重 | [GPT-SoVITS-Pretrained](https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained) | 部署脚本引用的基础模型 |
| 公开音色候选 | [2DIPW / ATRI_GPT-SoVITS](https://huggingface.co/2DIPW/ATRI_GPT-SoVITS) | 带上游使用限制的音色候选；使用前阅读模型卡 |
| 素材与候选记录 | [模型来源记录](voice-model-candidates.md) | 已记录的来源、版本、许可证与文件校验信息 |

参考音频应来自你自己录制或已获授权的素材。第三方角色音色、游戏素材和模型有各自的版权及使用条件；本仓库的代码发布不授予其素材许可。QQ 点歌也请自行准备允许使用的完整歌曲。

AI_music 是独立工程，本仓库不负责歌曲制作、训练或混音；Qbot 只发送用户已经放入歌单的成品。
