# 独立视频抽帧与画面解析

公共入口是 `atri_shared.video.VideoAnalyzer`。它接收已取得的视频字节、扩展名、绝对单调时钟截止时间，返回类型化证据；不读取账号、应用配置或聊天状态，不下载平台链接，不启动模型服务。

```python
import time
from atri_shared.video import VideoAnalyzer, VideoOptions

report = await VideoAnalyzer(options=VideoOptions(max_frames=4)).analyze(
    video_bytes, ".mp4", deadline=time.monotonic() + 60,
)
# 默认只抽帧；通过 ocr=、vision= 注入异步提供者来解析文字和画面。
print(report.visual_status, report.issues)
```

- `models.py`：不可变输入选项、帧、OCR 文字、阶段错误和分析结果。
- `extractor.py`：FFmpeg 子进程、时长探测、均匀采样、顺序回退、去重和资源清理。输入临时落盘，抽帧通过 `image2pipe` 直接返回内存。
- `service.py`：统一时间预算、提供者接口、阶段隔离和部分结果保留。
- `__main__.py`：不经过聊天应用的本地诊断命令。

运行依赖为项目已有的 `imageio-ffmpeg`、Pillow；Python 3.11 起。导入模块不会加载这些引擎，真正抽帧时才读取 FFmpeg/Pillow。并发槽位限制在同一事件循环内，默认为两个抽帧任务；不是跨进程资源调度器。

OCR 提供者接收图片字节，返回 `FrameText(text, error)`；视觉提供者接收有序 `tuple[VideoFrame, ...]` 和 OCR `tuple[VideoText, ...]`，同样返回 `FrameText`。通过 `FrameExtractor` 协议可替换抽帧后端，无需继承聊天对象。提供者必须配合异步取消；不能保证取消底层已提交到线程或远程推理服务的工作。

`VideoIssue(stage, code, message)` 区分 `probe`、`extract`、`ocr`、`vision`，常见代码包含 `timeout`、`invalid_input`、`unavailable`、`decode_failed`、`partial_frames`、`sequential_fallback`、`provider_error`、`failed`、`disabled`、`no_frames`。有错误不一定没有结果，应分别读取证据与错误。

`timestamp_seconds` 是请求 FFmpeg 的近似采样位置，不是帧级精确 PTS。去重后保留原位置；顺序回退位置为 `None`，仅覆盖开头片段，禁止重新标成“开头到结尾均匀采样”。`verified` 沿用现有视觉结果状态，表示视觉提供者返回内容，不代表外部事实核验或完整观看。

在仓库根目录独立诊断：

```powershell
& .venv/Scripts/python.exe -m atri_shared.video "D:\素材\example.mp4" --frames 4 --seconds 24
# 可选保存 JPEG 和 report.json；输出目录必须尚不存在
& .venv/Scripts/python.exe -m atri_shared.video "D:\素材\example.mp4" --output dev/workspace/video-check
& .venv/Scripts/python.exe -m pytest -q dev/tests/test_video_analysis.py dev/tests/test_media_probe_processes.py
```

详细架构、历史修复和验收边界见 [视频能力维护记录](../../../../docs/engineering/modules/video-analysis.md)。修改本模块前先读该记录，修复后同步更新记录和真实失败路径对应的测试。
