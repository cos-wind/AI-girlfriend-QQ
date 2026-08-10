import asyncio
from contextlib import asynccontextmanager
import http.server
import json
import threading
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from atri_qq_bot.config import BotConfig
from atri_qq_bot.persona import AtriReplyEngine
from atri_qq_bot.runtime.inference_lock import _InterprocessFileLock
import atri_qq_bot.toolbox as toolbox_module
from atri_qq_bot.toolbox_parts import ocr as ocr_module
from atri_qq_bot.toolbox import (
    ToolAnalysisResult,
    ToolAnalyzer,
    _VisionModelResponse,
    _demote_unverified_visual_identity,
    _prepare_images_for_vision,
    _search_result_supports_query,
    _visual_prompt_for_kind,
    _visual_search_query,
)


def _config(tmp_path: Path) -> BotConfig:
    return BotConfig(
        bot_qq=100000001,
        host="127.0.0.1",
        port=8765,
        reply_mode="smart",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        temperature=0.8,
        max_tokens=350,
        memory_path=tmp_path / "memory.json",
    )


def test_toolbox_reads_text_document_and_disabled_model_reports_error(tmp_path) -> None:
    doc = tmp_path / "note.txt"
    doc.write_text("今天研究主题：睡眠不足会影响注意力。建议先补觉，再做高强度任务。", encoding="utf-8")
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"帮我总结这个文档 {doc}"))
    engine = AtriReplyEngine(_config(tmp_path))
    reply = asyncio.run(
        engine.reply("private:10001", f"帮我总结这个文档 {doc}", tool_context=context)
    )

    assert context is not None
    assert context.category == "生活学术研究"
    assert "睡眠不足" in context.prompt_context()
    assert "回复失败" in reply
    assert "未使用本地内容模板" in reply


def test_toolbox_reads_csv_as_research_data(tmp_path) -> None:
    csv = tmp_path / "score.csv"
    csv.write_text("name,score\nA,91\nB,82\n", encoding="utf-8")
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"分析表格数据 {csv}"))

    assert context is not None
    assert context.category == "生活学术研究"
    assert "2 行数据" in context.prompt_context()
    assert "name、score" in context.prompt_context()


def test_toolbox_reads_docx_without_external_dependency(tmp_path) -> None:
    docx = tmp_path / "report.docx"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>核心结论是先做小样本验证。</w:t></w:r></w:p></w:body>"
                "</w:document>"
            ),
        )
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"总结文档 {docx}"))

    assert context is not None
    assert "核心结论" in context.prompt_context()


def test_toolbox_reads_docx_headers_footers_and_comments(tmp_path) -> None:
    docx = tmp_path / "full-report.docx"
    xml_prefix = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    )
    xml_suffix = "</w:document>"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr(
            "word/document.xml",
            xml_prefix + "<w:body><w:p><w:r><w:t>正文结论：先做用户访谈。</w:t></w:r></w:p></w:body>" + xml_suffix,
        )
        archive.writestr(
            "word/header1.xml",
            xml_prefix + "<w:body><w:p><w:r><w:t>页眉项目：ATRI调研。</w:t></w:r></w:p></w:body>" + xml_suffix,
        )
        archive.writestr(
            "word/footer1.xml",
            xml_prefix + "<w:body><w:p><w:r><w:t>页脚版本：V2。</w:t></w:r></w:p></w:body>" + xml_suffix,
        )
        archive.writestr(
            "word/comments.xml",
            xml_prefix + "<w:body><w:p><w:r><w:t>批注：样本量需要扩大。</w:t></w:r></w:p></w:body>" + xml_suffix,
        )
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"深度总结这个文档 {docx}"))

    assert context is not None
    prompt = context.prompt_context()
    assert "正文结论" in prompt
    assert "页眉项目" in prompt
    assert "页脚版本" in prompt
    assert "样本量需要扩大" in prompt


def test_toolbox_reads_xlsx_without_external_dependency(tmp_path) -> None:
    xlsx = tmp_path / "data.xlsx"
    with zipfile.ZipFile(xlsx, "w") as archive:
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<sheetData>"
                '<row r="1"><c r="A1" t="inlineStr"><is><t>日期</t></is></c>'
                '<c r="B1" t="inlineStr"><is><t>销量</t></is></c></row>'
                '<row r="2"><c r="A2" t="inlineStr"><is><t>周一</t></is></c><c r="B2"><v>12</v></c></row>'
                "</sheetData></worksheet>"
            ),
        )
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"分析表格 {xlsx}"))

    assert context is not None
    assert "Excel 表格" in context.prompt_context()
    assert "日期、销量" in context.prompt_context()


def test_toolbox_reads_multiple_xlsx_sheets_and_numeric_summary(tmp_path) -> None:
    xlsx = tmp_path / "multi.xlsx"
    with zipfile.ZipFile(xlsx, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                "<sheets>"
                '<sheet name="销量" sheetId="1" r:id="rId1"/>'
                '<sheet name="成本" sheetId="2" r:id="rId2"/>'
                "</sheets></workbook>"
            ),
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                '<Relationship Id="rId2" Target="worksheets/sheet2.xml"/>'
                "</Relationships>"
            ),
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                '<row r="1"><c r="A1" t="inlineStr"><is><t>商品</t></is></c><c r="B1" t="inlineStr"><is><t>销量</t></is></c></row>'
                '<row r="2"><c r="A2" t="inlineStr"><is><t>A</t></is></c><c r="B2"><v>10</v></c></row>'
                '<row r="3"><c r="A3" t="inlineStr"><is><t>B</t></is></c><c r="B3"><v>20</v></c></row>'
                "</sheetData></worksheet>"
            ),
        )
        archive.writestr(
            "xl/worksheets/sheet2.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                '<row r="1"><c r="A1" t="inlineStr"><is><t>商品</t></is></c><c r="B1" t="inlineStr"><is><t>成本</t></is></c></row>'
                '<row r="2"><c r="A2" t="inlineStr"><is><t>A</t></is></c><c r="B2"><v>3</v></c></row>'
                '<row r="3"><c r="A3" t="inlineStr"><is><t>B</t></is></c><c r="B3"><v>8</v></c></row>'
                "</sheetData></worksheet>"
            ),
        )
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"分析表格数据 {xlsx}"))

    assert context is not None
    prompt = context.prompt_context()
    assert "读取到 2 个工作表" in prompt
    assert "工作表 销量" in prompt
    assert "工作表 成本" in prompt
    assert "销量 count=2 min=10 max=20 avg=15" in prompt
    assert "成本 count=2 min=3 max=8 avg=5.50" in prompt


def test_toolbox_reads_csv_quoted_commas_and_numeric_summary(tmp_path) -> None:
    csv_file = tmp_path / "quoted.csv"
    csv_file.write_text('name,comment,score\nA,"喜欢,但有点贵",91\nB,"稳定",82\n', encoding="utf-8")
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"分析这个表格 {csv_file}"))

    assert context is not None
    prompt = context.prompt_context()
    assert "name、comment、score" in prompt
    assert "喜欢,但有点贵" in prompt
    assert "score count=2 min=82 max=91 avg=86.50" in prompt


def test_toolbox_reads_local_png_metadata_when_user_asks_to_analyze_image(tmp_path) -> None:
    png = tmp_path / "shot.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x02\x00\x00\x00\x03"
        b"\x08\x06\x00\x00\x00\x00\x00\x00\x00"
    )
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"分析图片 {png}"))

    assert context is not None
    assert context.category == "日常生活乐趣"
    assert "2x3" in context.prompt_context()
    assert "不乱编" in context.prompt_context() or "臆测" in context.prompt_context()


def test_toolbox_uses_vision_analysis_for_images(monkeypatch, tmp_path) -> None:
    png = tmp_path / "shot.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x02\x00\x00\x00\x03"
        b"\x08\x06\x00\x00\x00\x00\x00\x00\x00"
    )
    analyzer = ToolAnalyzer(_config(tmp_path))

    async def fake_vision(data: bytes, source: str, prompt: str | None = None) -> tuple[str, str]:
        assert data
        assert source.endswith("shot.png")
        return "画面像清晨房间截图，色调干净，可以夸一句很有生活感。", ""

    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", fake_vision)

    context = asyncio.run(analyzer.analyze({"message": ""}, f"评价这张图 {png}"))

    assert context is not None
    prompt = context.prompt_context()
    assert "图片内容分析" in prompt
    assert "清晨房间截图" in prompt
    assert "生活感" in prompt
    assert "优先围绕当前画面或表情情绪回复" in prompt
    assert context.visual_status == "verified"


def test_analyze_propagates_visual_failure_status(monkeypatch, tmp_path) -> None:
    from PIL import Image
    import io

    source = io.BytesIO()
    Image.new("RGB", (160, 120), "white").save(source, format="PNG")
    image_path = tmp_path / "failed.png"
    image_path.write_bytes(source.getvalue())
    analyzer = ToolAnalyzer(_config(tmp_path))

    async def failed_vision(data: bytes, source: str, prompt: str | None = None):
        return "", "视觉模型没有返回可用图片分析。"

    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", failed_vision)

    context = asyncio.run(
        analyzer.analyze(
            {
                "message": [
                    {"type": "image", "data": {"file": str(image_path)}}
                ]
            },
            "这张图是什么意思？",
        )
    )

    assert context is not None
    assert context.visual_status == "unavailable"
    assert context.requires_visual_fail_safe()


def test_toolbox_routes_mface_image_to_sticker_emotion_analysis(monkeypatch, tmp_path) -> None:
    png = tmp_path / "atri_mface.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x30\x00\x00\x00\x30"
        b"\x08\x06\x00\x00\x00\x00\x00\x00\x00"
    )
    event = {"message": [{"type": "mface", "data": {"summary": "亚托莉叉腰生气", "file": str(png)}}]}
    analyzer = ToolAnalyzer(_config(tmp_path))

    async def fake_vision(data: bytes, source: str, prompt: str | None = None) -> tuple[str, str]:
        assert "表情包/梗图/动画表情" in (prompt or "")
        return "类型：表情包；情绪：生气但带点撒娇；画面：角色叉腰；适合怎么接话：可以顺着哄她。", ""

    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", fake_vision)

    context = asyncio.run(analyzer.analyze(event, "[动画表情:亚托莉叉腰生气]"))

    assert context is not None
    prompt = context.prompt_context()
    assert "表情包信息" in prompt
    assert "表情包情绪分析" in prompt
    assert "生气但带点撒娇" in prompt


def test_toolbox_fetches_mface_through_onebot_image_action(monkeypatch, tmp_path) -> None:
    image = tmp_path / "market-face.gif"
    image.write_bytes(b"GIF89a" + b"\x00" * 32)
    event = {
        "message": [
            {"type": "mface", "data": {"summary": "animated sticker", "file": "market-face.gif"}}
        ]
    }
    analyzer = ToolAnalyzer(_config(tmp_path))
    actions: list[str] = []

    async def fake_action(action: str, params: dict) -> dict:
        actions.append(action)
        assert params["file"] == "market-face.gif"
        return {
            "status": "ok",
            "data": {
                "url": "http://127.0.0.1:1/unreachable.gif",
                "file": str(image),
            },
        }

    async def fake_vision(data: bytes, source: str, prompt: str | None = None) -> tuple[str, str]:
        assert data.startswith(b"GIF89a")
        assert source == str(image)
        return "类型：表情包；画面文字：测试成功；情绪：开心。", ""

    async def fail_remote(url: str, filename_hint: str = "") -> tuple[bytes, str, str]:
        raise OSError("simulated CDN failure")

    monkeypatch.setattr(analyzer, "_fetch_url", fail_remote)
    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", fake_vision)

    context = asyncio.run(analyzer.analyze(event, "[sticker]", fake_action))

    assert context is not None
    assert context.read_level == "full_content"
    assert actions == ["get_image"]
    assert "测试成功" in context.prompt_context()


def test_toolbox_filters_garbage_vision_output(monkeypatch, tmp_path) -> None:
    png = tmp_path / "screen.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x03\x20\x00\x00\x02\x58"
        b"\x08\x06\x00\x00\x00\x00\x00\x00\x00"
    )
    analyzer = ToolAnalyzer(_config(tmp_path))

    async def fake_vision(data: bytes, source: str, prompt: str | None = None) -> tuple[str, str]:
        return (
            "<think>先分析一下</think>\n"
            "analysis: hidden tool process\n"
            "QWERTY12345:/==++++\n"
            "类型：普通图片；主体/场景：游戏界面截图；关键文字或UI：能看到角色和按钮。"
        ), ""

    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", fake_vision)

    context = asyncio.run(analyzer.analyze({"message": ""}, f"分析这张图 {png}"))

    assert context is not None
    prompt = context.prompt_context()
    assert "图片内容分析" in prompt
    assert "游戏界面截图" in prompt
    assert "analysis" not in prompt.lower()
    assert "QWERTY12345" not in prompt


def test_toolbox_keeps_independent_ocr_when_vision_is_temporarily_unavailable(
    monkeypatch,
    tmp_path,
) -> None:
    from PIL import Image
    import io

    source = io.BytesIO()
    Image.new("RGB", (320, 180), "white").save(source, format="PNG")
    analyzer = ToolAnalyzer(_config(tmp_path))
    analyzer.ocr_enabled = True
    captured: dict[str, str] = {}

    async def fake_ocr(data: bytes):
        assert data == source.getvalue()
        return SimpleNamespace(
            text="不是很懂",
            average_confidence=0.97,
            error="",
        )

    async def failed_vision(data: bytes, source_name: str, prompt: str | None = None):
        captured["prompt"] = prompt or ""
        return "", "视觉模型资源繁忙。"

    monkeypatch.setattr(analyzer, "_extract_image_ocr", fake_ocr, raising=False)
    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", failed_vision)

    result = asyncio.run(
        analyzer._analyze_image_bytes(
            source.getvalue(),
            "meme.png",
            visual_kind="sticker",
        )
    )

    assert result.read_level == "partial_content"
    assert "独立 OCR 文字：不是很懂" in result.prompt_context()
    assert "独立 OCR 结果（文字证据）" in captured["prompt"]


def test_independent_ocr_overrides_conflicting_visual_model_text(
    monkeypatch,
    tmp_path,
) -> None:
    from PIL import Image
    import io

    source = io.BytesIO()
    Image.new("RGB", (320, 180), "white").save(source, format="PNG")
    analyzer = ToolAnalyzer(_config(tmp_path))
    analyzer.ocr_enabled = True

    async def fake_ocr(data: bytes):
        return SimpleNamespace(
            text="停止 ATRI",
            average_confidence=0.98,
            line_count=1,
            error="",
        )

    async def fake_vision(data: bytes, source_name: str, prompt: str | None = None):
        return (
            "直接回答：这是菜单截图；图中文字：启动 ATRI；"
            "人物/主体：菜单；身份/出处：未确认；表情/情绪：中性；"
            "表达含义/社交意图：操作软件；依据：菜单文字；"
            "置信度：高；需要联网核验：否；检索关键词：",
            "",
        )

    monkeypatch.setattr(analyzer, "_extract_image_ocr", fake_ocr)
    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", fake_vision)

    result = asyncio.run(
        analyzer._analyze_image_bytes(source.getvalue(), "menu.png")
    )
    prompt = result.prompt_context()

    assert "图中文字：停止 ATRI" in prompt
    assert "图中文字：启动 ATRI" not in prompt


def test_ocr_rejects_tiny_image_ascii_noise_but_keeps_real_chinese_text() -> None:
    assert not ocr_module._plausible_ocr_candidate(
        "n G",
        0.99,
        minimum_confidence=0.55,
        tiny_source=True,
    )
    assert ocr_module._plausible_ocr_candidate(
        "不服",
        0.92,
        minimum_confidence=0.55,
        tiny_source=True,
    )


def test_ocr_prepares_color_and_contrast_variants_for_text_images() -> None:
    from PIL import Image, ImageDraw
    import io

    source = io.BytesIO()
    image = Image.new("RGB", (320, 120), (180, 190, 205))
    ImageDraw.Draw(image).text((16, 40), "ATRI 2026", fill=(105, 120, 135))
    image.save(source, format="PNG")

    prepared = ocr_module._prepare_ocr_frames(source.getvalue(), maximum_frames=1)

    assert len(prepared) == 2
    assert all(frame for frame, _ in prepared)


def test_ollama_vision_retries_transient_memory_allocation_failure(
    monkeypatch,
    tmp_path,
) -> None:
    from PIL import Image
    import io

    source = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(source, format="PNG")
    config = replace(
        _config(tmp_path),
        toolbox_vision_enabled=True,
        toolbox_vision_model="qwen3-vl:8b-instruct",
        toolbox_vision_base_url="http://127.0.0.1:11434/v1",
    )
    analyzer = ToolAnalyzer(config)
    analyzer.vision_retry_count = 1
    analyzer.vision_resource_wait_seconds = 1.0
    calls: list[str] = []

    @asynccontextmanager
    async def fake_lease(engine: str, *, timeout_seconds: float):
        calls.append(f"lease:{engine}:{timeout_seconds}")
        yield

    async def fake_native(encoded_images, system_prompt, user_prompt, model=None):
        calls.append("vision")
        if calls.count("vision") == 1:
            raise RuntimeError("memory layout cannot be allocated")
        return _VisionModelResponse(
            "直接回答：文字和表情都已识别；图中文字：测试成功；"
            "人物/主体：卡通人物；身份/出处：未确认；"
            "表情/情绪：开心；表达含义/社交意图：表示赞同；"
            "依据：微笑；置信度：中；需要联网核验：否；检索关键词：",
            {"provider": "ollama"},
        )

    async def fake_release(model=None) -> None:
        calls.append(f"release:{model or ''}")

    async def no_delay(seconds: float) -> None:
        calls.append(f"sleep:{seconds}")

    monkeypatch.setattr(
        toolbox_module,
        "inference_resource_lease",
        fake_lease,
        raising=False,
    )
    monkeypatch.setattr(analyzer, "_analyze_image_with_ollama_native", fake_native)
    monkeypatch.setattr(
        analyzer,
        "_release_vision_model_after_failure",
        fake_release,
        raising=False,
    )
    monkeypatch.setattr(toolbox_module.asyncio, "sleep", no_delay)

    text, limitation = asyncio.run(
        analyzer._analyze_image_with_vision(
            source.getvalue(),
            "resource-test.png",
        )
    )

    assert "测试成功" in text
    assert limitation == ""
    assert calls.count("vision") == 2
    assert any(item.startswith("release:") for item in calls)


def test_ollama_vision_switches_to_fallback_model_after_resource_failure(
    monkeypatch,
    tmp_path,
) -> None:
    from PIL import Image
    import io

    source = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(source, format="PNG")
    config = replace(
        _config(tmp_path),
        toolbox_vision_enabled=True,
        toolbox_vision_model="qwen3-vl:8b-instruct",
        toolbox_vision_fallback_model="qwen3-vl:4b-instruct",
        toolbox_vision_base_url="http://127.0.0.1:11434/v1",
    )
    analyzer = ToolAnalyzer(config)
    analyzer.vision_retry_count = 1
    analyzer.vision_resource_wait_seconds = 1.0
    called_models: list[str] = []

    @asynccontextmanager
    async def fake_lease(engine: str, *, timeout_seconds: float):
        yield

    async def fake_native(
        encoded_images,
        system_prompt,
        user_prompt,
        model=None,
    ):
        called_models.append(model)
        if model == "qwen3-vl:8b-instruct":
            raise RuntimeError("memory layout cannot be allocated")
        return _VisionModelResponse(
            "直接回答：这是一个开心赞同的表情包；图中文字：无明显文字；"
            "人物/主体：卡通人物；身份/出处：未确认；"
            "表情/情绪：开心；表达含义/社交意图：表示赞同；"
            "依据：微笑；置信度：中；需要联网核验：否；检索关键词：",
            {"provider": "ollama"},
        )

    async def no_op(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(
        toolbox_module,
        "inference_resource_lease",
        fake_lease,
        raising=False,
    )
    monkeypatch.setattr(analyzer, "_analyze_image_with_ollama_native", fake_native)
    monkeypatch.setattr(
        analyzer,
        "_release_vision_model_after_failure",
        no_op,
        raising=False,
    )
    monkeypatch.setattr(toolbox_module.asyncio, "sleep", no_op)

    text, limitation = asyncio.run(
        analyzer._analyze_image_with_vision(
            source.getvalue(),
            "fallback-test.png",
        )
    )

    assert "开心赞同" in text
    assert limitation == ""
    assert called_models == [
        "qwen3-vl:8b-instruct",
        "qwen3-vl:4b-instruct",
    ]


def test_ollama_vision_switches_to_fallback_after_empty_truncated_output(
    monkeypatch,
    tmp_path,
) -> None:
    from PIL import Image
    import io

    source = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(source, format="PNG")
    config = replace(
        _config(tmp_path),
        toolbox_vision_enabled=True,
        toolbox_vision_model="qwen3-vl:8b",
        toolbox_vision_fallback_model="qwen3-vl:4b-instruct",
        toolbox_vision_base_url="http://127.0.0.1:11434/v1",
    )
    analyzer = ToolAnalyzer(config)
    analyzer.vision_retry_count = 1
    called_models: list[str] = []

    @asynccontextmanager
    async def fake_lease(engine: str, *, timeout_seconds: float):
        yield

    async def fake_native(
        encoded_images,
        system_prompt,
        user_prompt,
        model=None,
    ):
        called_models.append(model)
        if model == "qwen3-vl:8b":
            return _VisionModelResponse(
                "",
                {
                    "provider": "ollama",
                    "done_reason": "length",
                    "eval_count": 320,
                },
            )
        return _VisionModelResponse(
            "直接回答：这是测试图片；图中文字：测试成功；"
            "人物/主体：测试卡片；身份/出处：未确认；"
            "表情/情绪：中性；表达含义/社交意图：展示测试结果；"
            "依据：独立 OCR 与画面一致；置信度：高；"
            "需要联网核验：否；检索关键词：",
            {"provider": "ollama", "done_reason": "stop"},
        )

    async def no_op(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(
        toolbox_module,
        "inference_resource_lease",
        fake_lease,
        raising=False,
    )
    monkeypatch.setattr(analyzer, "_analyze_image_with_ollama_native", fake_native)
    monkeypatch.setattr(
        analyzer,
        "_release_vision_model_after_failure",
        no_op,
        raising=False,
    )
    monkeypatch.setattr(toolbox_module.asyncio, "sleep", no_op)

    text, limitation = asyncio.run(
        analyzer._analyze_image_with_vision(
            source.getvalue(),
            "truncated-test.png",
        )
    )

    assert "测试成功" in text
    assert limitation == ""
    assert called_models == ["qwen3-vl:8b", "qwen3-vl:4b-instruct"]


def test_unavailable_visual_evidence_requires_deterministic_fail_safe() -> None:
    context = ToolAnalysisResult(
        category="日常生活乐趣",
        style="抽象有趣",
        findings=["图片信息：PNG 格式，尺寸约 640x480。"],
        limitations=["视觉模型没有返回可用图片分析。"],
        read_level="metadata_only",
        visual_kind="image",
        visual_status="unavailable",
    )

    assert context.requires_visual_fail_safe()
    reply = context.visual_failure_reply()
    assert "没有稳定识别" in reply
    assert "不乱猜" in reply
    assert "看到" not in reply


def test_reply_engine_bypasses_chat_model_when_visual_evidence_is_unavailable(
    monkeypatch,
    tmp_path,
) -> None:
    engine = AtriReplyEngine(replace(_config(tmp_path), openai_api_key="test-key"))
    context = ToolAnalysisResult(
        category="日常生活乐趣",
        style="抽象有趣",
        findings=["图片信息：JPEG 格式，尺寸约 200x200。"],
        limitations=["视觉模型没有返回可用图片分析。"],
        read_level="metadata_only",
        visual_kind="image",
        visual_status="unavailable",
    )

    async def must_not_call_model(*args, **kwargs):
        raise AssertionError("视觉失败后不应再让聊天模型自由生成")

    monkeypatch.setattr(engine, "_reply_with_guarded_api", must_not_call_model)

    wrapped_context = SimpleNamespace(material_context=context)
    reply = asyncio.run(
        engine.reply(
            "private:visual-fail-safe",
            "这张图是什么意思？",
            tool_context=wrapped_context,
        )
    )

    assert "没有稳定识别" in reply
    assert "不乱猜" in reply


def test_vision_releases_stale_ollama_models_before_loading(monkeypatch, tmp_path) -> None:
    import httpx

    analyzer = ToolAnalyzer(_config(tmp_path))
    analyzer.vision_base_url = "http://127.0.0.1:11434/v1"
    analyzer.vision_model = "qwen3-vl:8b-instruct"
    analyzer.chat_base_url = "https://api.example.invalid/v1"
    analyzer.chat_model = "remote-chat"
    analyzer.vision_unload_other_ollama_models = True
    released: list[str] = []

    class FakeResponse:
        def __init__(self, body: dict | None = None) -> None:
            self._body = body or {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._body

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            return None

        async def get(self, url: str) -> FakeResponse:
            assert url.endswith("/api/ps")
            return FakeResponse(
                {
                    "models": [
                        {"name": "qwen3:4b-instruct"},
                        {"name": "qwen3-vl:8b-instruct"},
                    ]
                }
            )

        async def post(self, url: str, json: dict) -> FakeResponse:
            assert url.endswith("/api/generate")
            assert json["keep_alive"] == 0
            released.append(json["model"])
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    asyncio.run(analyzer._release_chat_model_for_vision())

    assert released == ["qwen3:4b-instruct"]


def test_gpu_inference_file_lock_serializes_independent_runtimes(tmp_path) -> None:
    lock_path = tmp_path / "gpu.lock"
    first = _InterprocessFileLock(lock_path)
    second = _InterprocessFileLock(lock_path)
    acquired = threading.Event()
    errors: list[Exception] = []

    first.acquire(0.0)

    def acquire_second() -> None:
        try:
            second.acquire(2.0)
            acquired.set()
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=acquire_second, daemon=True)
    worker.start()
    assert acquired.wait(0.15) is False
    first.release()
    assert acquired.wait(1.0) is True
    second.release()
    worker.join(timeout=1.0)

    assert errors == []


def test_toolbox_analyzes_image_when_user_asks_natural_evaluation(tmp_path) -> None:
    served = tmp_path / "served_natural_image"
    served.mkdir()
    (served / "photo.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x06\x00\x00\x00\x07"
        b"\x08\x06\x00\x00\x00\x00\x00\x00\x00"
    )

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    old_cwd = __import__("os").getcwd()
    __import__("os").chdir(served)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        image_url = f"http://127.0.0.1:{server.server_port}/photo.png"
        event = {"message": [{"type": "image", "data": {"file": "photo.png", "url": image_url}}]}
        analyzer = ToolAnalyzer(_config(tmp_path))
        context = asyncio.run(analyzer.analyze(event, "这张怎么样"))
    finally:
        server.shutdown()
        __import__("os").chdir(old_cwd)

    assert context is not None
    assert "6x7" in context.prompt_context()


def test_toolbox_fetches_webpage_from_local_server(tmp_path) -> None:
    served = tmp_path / "served"
    served.mkdir()
    (served / "index.html").write_text(
        "<html><head><title>研究页面</title><meta name='description' content='这是简介'></head>"
        "<body><main>正文说今天的数据需要先核对来源，再比较趋势。</main></body></html>",
        encoding="utf-8",
    )

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    old_cwd = __import__("os").getcwd()
    __import__("os").chdir(served)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/index.html"
        analyzer = ToolAnalyzer(_config(tmp_path))
        context = asyncio.run(analyzer.analyze({"message": ""}, f"查询权威资料 {url}"))
    finally:
        server.shutdown()
        __import__("os").chdir(old_cwd)

    assert context is not None
    assert "研究页面" in context.prompt_context()
    assert "核对来源" in context.prompt_context()


def test_toolbox_recognizes_bilibili_material_from_api(monkeypatch, tmp_path) -> None:
    analyzer = ToolAnalyzer(_config(tmp_path))

    async def fake_fetch(url: str) -> tuple[bytes, str, str]:
        if "x/web-interface/view" in url:
            return (
                json.dumps(
                    {
                        "data": {
                            "title": "高能整活视频",
                            "owner": {"name": "UP主A"},
                            "tname": "搞笑",
                            "desc": "这个视频主打生活整活。",
                            "stat": {"view": 100, "like": 20},
                            "pages": [{"part": "正片", "cid": 123}],
                        }
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                url,
                "application/json",
            )
        if "x/player/v2" in url:
            return (json.dumps({"data": {"subtitle": {"subtitles": []}}}).encode("utf-8"), url, "application/json")
        return (
            b"<html><head><title>video</title></head></html>",
            "https://www.bilibili.com/video/BV1abcabcabc",
            "text/html",
        )

    monkeypatch.setattr(analyzer, "_fetch_url", fake_fetch)

    context = asyncio.run(
        analyzer.analyze({"message": ""}, "分析这个b站视频 https://www.bilibili.com/video/BV1abcabcabc")
    )

    assert context is not None
    assert context.category == "日常生活乐趣"
    assert "抽象有趣" in context.prompt_context()
    assert "高能整活视频" in context.prompt_context()
    assert "UP主A" in context.prompt_context()


def test_toolbox_reads_mobile_file_segment_with_url(tmp_path) -> None:
    served = tmp_path / "served_file"
    served.mkdir()
    (served / "mobile-note.txt").write_text("移动端直发文件内容：今天要先完成项目调试。", encoding="utf-8")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    old_cwd = __import__("os").getcwd()
    __import__("os").chdir(served)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/mobile-note.txt"
        event = {
            "message": [
                {"type": "text", "data": {"text": "帮我总结这个文件"}},
                {"type": "file", "data": {"name": "mobile-note.txt", "url": url}},
            ]
        }
        analyzer = ToolAnalyzer(_config(tmp_path))
        context = asyncio.run(analyzer.analyze(event, "帮我总结这个文件[文件:mobile-note.txt]"))
    finally:
        server.shutdown()
        __import__("os").chdir(old_cwd)

    assert context is not None
    assert context.category == "生活学术研究"
    assert "移动端直发文件内容" in context.prompt_context()
    assert "项目调试" in context.prompt_context()


def test_toolbox_uses_mobile_filename_when_download_url_has_no_extension(tmp_path) -> None:
    served = tmp_path / "served_no_ext"
    served.mkdir()
    real_doc = served / "download"
    with zipfile.ZipFile(real_doc, "w") as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>无后缀链接里的DOCX正文。</w:t></w:r></w:p></w:body>"
                "</w:document>"
            ),
        )

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    old_cwd = __import__("os").getcwd()
    __import__("os").chdir(served)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/download"
        event = {
            "message": [
                {"type": "file", "data": {"name": "手机文档.docx", "url": url}},
            ]
        }
        analyzer = ToolAnalyzer(_config(tmp_path))
        context = asyncio.run(analyzer.analyze(event, "[文件:手机文档.docx]"))
    finally:
        server.shutdown()
        __import__("os").chdir(old_cwd)

    assert context is not None
    assert "无后缀链接里的DOCX正文" in context.prompt_context()


def test_toolbox_reads_mobile_file_segment_through_onebot_action(monkeypatch, tmp_path) -> None:
    served = tmp_path / "served_action_file"
    served.mkdir()
    (served / "action-note.txt").write_text("通过 NapCat file_id 取得的正文。", encoding="utf-8")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    old_cwd = __import__("os").getcwd()
    __import__("os").chdir(served)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/action-note.txt"
        event = {
            "message": [
                {"type": "file", "data": {"name": "action-note.txt", "file_id": "file-123"}}
            ]
        }
        analyzer = ToolAnalyzer(_config(tmp_path))

        async def fake_action(action: str, params: dict) -> dict:
            assert action == "get_file"
            assert params.get("file_id") == "file-123"
            return {"status": "ok", "retcode": 0, "data": {"url": url}}

        context = asyncio.run(analyzer.analyze(event, "[文件:action-note.txt]", fake_action))
    finally:
        server.shutdown()
        __import__("os").chdir(old_cwd)

    assert context is not None
    assert "通过 NapCat file_id" in context.prompt_context()


def test_toolbox_reads_bilibili_mobile_share_card(monkeypatch, tmp_path) -> None:
    analyzer = ToolAnalyzer(_config(tmp_path))

    async def fake_fetch(url: str) -> tuple[bytes, str, str]:
        if "x/web-interface/view" in url:
            return (
                json.dumps(
                    {
                        "data": {
                            "title": "嫉妒使人面目全非",
                            "owner": {"name": "罗翔说刑法"},
                            "tname": "知识",
                            "desc": "如何面对嫉妒的公开简介。",
                            "stat": {"view": 200, "like": 30},
                            "pages": [{"part": "正片", "cid": 456}],
                        }
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                url,
                "application/json",
            )
        if "x/player/v2" in url:
            return (json.dumps({"data": {"subtitle": {"subtitles": []}}}).encode("utf-8"), url, "application/json")
        return (
            b"<html><head><title>video</title></head></html>",
            "https://www.bilibili.com/video/BV1abcabcabc",
            "text/html",
        )

    monkeypatch.setattr(analyzer, "_fetch_url", fake_fetch)
    share_payload = {
        "meta": {
            "detail_1": {
                "title": "罗翔：如何面对嫉妒",
                "qqdocurl": "https://www.bilibili.com/video/BV1abcabcabc",
            }
        }
    }
    event = {"message": [{"type": "json", "data": {"data": json.dumps(share_payload, ensure_ascii=False)}}]}

    context = asyncio.run(analyzer.analyze(event, "[分享:罗翔：如何面对嫉妒]"))

    assert context is not None
    assert context.category == "日常生活乐趣"
    assert "嫉妒使人面目全非" in context.prompt_context()
    assert "罗翔说刑法" in context.prompt_context()


def test_toolbox_handles_direct_image_and_plain_video_without_hallucinating(tmp_path) -> None:
    served = tmp_path / "served_media"
    served.mkdir()
    (served / "shot.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x04\x00\x00\x00\x05"
        b"\x08\x06\x00\x00\x00\x00\x00\x00\x00"
    )

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    old_cwd = __import__("os").getcwd()
    __import__("os").chdir(served)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        image_url = f"http://127.0.0.1:{server.server_port}/shot.png"
        event = {
            "message": [
                {"type": "image", "data": {"file": "shot.png", "url": image_url}},
                {"type": "video", "data": {"title": "手机发来的视频"}},
            ]
        }
        analyzer = ToolAnalyzer(_config(tmp_path))
        context = asyncio.run(analyzer.analyze(event, "[表情包/图片:shot.png][视频:手机发来的视频]"))
    finally:
        server.shutdown()
        __import__("os").chdir(old_cwd)

    assert context is not None
    prompt = context.prompt_context()
    assert "4x5" in prompt
    assert "手机发来的视频" in prompt
    assert "不会臆测图片里具体画面" in prompt
    assert "暂不自动下载和解析画面" in prompt


def test_toolbox_marks_title_only_video_as_metadata_only(tmp_path) -> None:
    event = {
        "message": [
            {"type": "video", "data": {"title": "手机发来的视频"}}
        ]
    }
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze(event, "[视频:手机发来的视频]"))

    assert context is not None
    assert context.read_level == "metadata_only"
    prompt = context.prompt_context()
    assert "只读到标题" in prompt
    assert "禁止说“我看完了视频”" in prompt
    assert "手机发来的视频" in prompt


def test_metadata_only_result_detects_claims_about_unread_content() -> None:
    context = ToolAnalysisResult(
        category="娱乐吐槽",
        style="casual",
        findings=["只读到标题：手机发来的视频"],
        limitations=["没有读取视频画面或声音"],
        read_level="metadata_only",
    )

    assert context.needs_grounding_repair("我点进去看了，视频里讲得挺清楚")
    assert context.needs_grounding_repair("这个旋律听起来很上头")
    assert context.needs_grounding_repair("我盯着图看了半天，但图片像素太低，看不清")
    assert not context.needs_grounding_repair("我这里只读到了标题，暂时判断不了画面内容")


def test_visual_followup_reanalyzes_the_original_image(monkeypatch, tmp_path) -> None:
    analyzer = ToolAnalyzer(_config(tmp_path))
    previous = ToolAnalysisResult(
        category="visual",
        style="casual",
        sources=["previous.png"],
        visual_data=b"original-image-bytes",
        visual_source="previous.png",
        visual_kind="image",
    )
    captured: dict[str, object] = {}

    async def fake_vision(data: bytes, source: str, prompt: str | None = None):
        captured.update(data=data, source=source, prompt=prompt)
        return "\u4eba\u7269\u662f\u4e30\u5ddd\u7965\u5b50\u3002", ""

    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", fake_vision)

    result = asyncio.run(
        analyzer.analyze_visual_followup(previous, "\u8fd9\u4e2a\u662f\u8c01\uff1f")
    )

    assert result is not None
    assert result.read_level == "full_content"
    assert "\u4e30\u5ddd\u7965\u5b50" in result.prompt_context()
    assert captured["data"] == b"original-image-bytes"
    assert "\u8fd9\u4e2a\u662f\u8c01" in str(captured["prompt"])


def test_current_visual_question_is_sent_with_the_current_image(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "current.jpg"
    image_path.write_bytes(b"current-image-bytes")
    analyzer = ToolAnalyzer(_config(tmp_path))
    captured: dict[str, object] = {}

    async def fake_vision(data: bytes, source: str, prompt: str | None = None):
        captured.update(data=data, source=source, prompt=prompt)
        return (
            "直接回答：这是初音未来。\n"
            "图中文字：无明显文字。\n"
            "身份/出处：初音未来。\n"
            "置信度：高。\n"
            "需要联网核验：否。",
            "",
        )

    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", fake_vision)
    event = {
        "message": [
            {"type": "text", "data": {"text": "这是谁？请说明依据"}},
            {"type": "image", "data": {"file": str(image_path)}},
        ]
    }

    result = asyncio.run(analyzer.analyze(event, "这是谁？请说明依据[表情包/图片:current.jpg]"))

    assert result is not None
    prompt = str(captured["prompt"])
    assert captured["data"] == b"current-image-bytes"
    assert "这是谁？请说明依据" in prompt
    assert "直接回答" in prompt
    assert "身份/出处" in prompt
    assert "表达含义/社交意图" in prompt
    assert "需要联网核验" in prompt


def test_animated_visual_is_sent_as_independent_readable_frames() -> None:
    from PIL import Image
    import io

    frames = [
        Image.new("RGB", (1200, 900), color)
        for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0))
    ]
    source = io.BytesIO()
    frames[0].save(
        source,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=80,
        loop=0,
    )

    prepared = _prepare_images_for_vision(source.getvalue())

    assert len(prepared) == 3
    for frame_data in prepared:
        with Image.open(io.BytesIO(frame_data)) as frame:
            assert max(frame.size) == 768
            assert frame.size != (960, 960)


def test_visual_search_query_comes_from_structured_uncertainty() -> None:
    assert _visual_search_query(
        "身份/出处：疑似某动画角色；置信度：低；"
        "需要联网核验：是；检索关键词：绿色短发 校服 吉他 动漫角色"
    ) == "绿色短发 校服 吉他 动漫角色"
    assert not _visual_search_query(
        "身份/出处：初音未来；置信度：高；"
        "需要联网核验：否；检索关键词：初音未来"
    )
    assert not _search_result_supports_query(
        "标题：初音未来角色介绍",
        "初音未来 表情包 绿色双马尾",
    )
    assert _search_result_supports_query(
        "标题：初音未来角色介绍\n摘要：绿色双马尾虚拟歌手形象。",
        "初音未来 虚拟歌手 绿色双马尾",
    )
    assert not _search_result_supports_query(
        "标题：汉字“初”的解释",
        "初音未来 表情包 绿色双马尾",
    )
    assert not _search_result_supports_query(
        "搜索关键词：星野爱 我推的孩子 表情包\n"
        "聚合来源：Bing Web\n"
        "1. 标题：星（汉语文字）_百度百科\n"
        "摘要：星是夜空中的发光天体。",
        "星野爱 我推的孩子 表情包",
    )
    demoted = _demote_unverified_visual_identity(
        "人物/主体：粉发少女；身份/出处：疑似星野爱；"
        "表情/情绪：无奈；依据：造型符合星野爱；置信度：中；"
        "检索关键词：星野爱 我推的孩子 表情包"
    )
    assert "星野爱" not in demoted
    assert "身份/出处：未确认" in demoted
    assert "表情/情绪：无奈" in demoted
    assert "依据：人物身份未获可靠核验" in demoted
    assert "检索关键词：无可靠匹配" in demoted


def test_visual_prompt_removes_nested_qq_image_placeholder() -> None:
    prompt = _visual_prompt_for_kind(
        "sticker",
        "[表情包/图片:[动画表情]]",
    )

    assert "当前用户问题：用户没有附加文字，请完整理解图片。" in prompt
    assert "当前用户问题：]" not in prompt


def test_normal_reply_repairs_material_claim_once(monkeypatch, tmp_path) -> None:
    config = replace(_config(tmp_path), openai_api_key="test-key")
    engine = AtriReplyEngine(config)
    context = ToolAnalysisResult(
        category="娱乐吐槽",
        style="casual",
        findings=["只读到标题：手机发来的视频"],
        limitations=["没有读取视频画面或声音"],
        read_level="metadata_only",
    )
    replies = iter(
        [
            "我点进去看了，视频里的旋律挺上头。",
            "我这里只读到了标题，还判断不了画面和声音。你更想聊它的哪一部分？",
        ]
    )
    calls: list[dict[str, object]] = []

    async def fake_guarded_api(*args, **kwargs):
        calls.append(kwargs)
        return next(replies)

    monkeypatch.setattr(engine, "_reply_with_guarded_api", fake_guarded_api)

    reply = asyncio.run(
        engine.reply(
            "private:10001",
            "你看看这个视频",
            tool_context=context,
        )
    )

    assert len(calls) == 2
    assert calls[1]["allow_reply_voice"] is False
    assert "只读到了标题" in reply
    assert not context.needs_grounding_repair(reply)


def test_toolbox_reads_mobile_video_through_onebot_action(monkeypatch, tmp_path) -> None:
    video_file = tmp_path / "clip.mp4"
    video_file.write_bytes(b"fake-video")
    event = {
        "message": [
            {"type": "video", "data": {"title": "手机发来的视频", "file_id": "video-123"}}
        ]
    }
    config = _config(tmp_path)
    analyzer = ToolAnalyzer(config)
    analyzer.vision_enabled = True

    async def fake_action(action: str, params: dict) -> dict:
        assert action in {"get_file", "get_private_file_url"}
        assert params.get("file_id") == "video-123" or params.get("file") == "video-123"
        return {"status": "ok", "data": {"path": str(video_file)}}

    def fake_extract(data: bytes, ext: str, max_frames: int) -> tuple[list[bytes], str]:
        assert data == b"fake-video"
        assert max_frames == config.toolbox_video_max_frames
        return [
            b"\xff\xd8\xff\xe0" + b"0" * 32,
            b"\xff\xd8\xff\xe0" + b"1" * 32,
        ], ""

    vision_calls: list[dict[str, object]] = []

    async def fake_vision(
        data: bytes,
        source: str,
        prompt: str | None = None,
        **kwargs,
    ) -> tuple[str, str]:
        vision_calls.append({"source": source, "prompt": prompt, **kwargs})
        return "看到人物在室内展示物品，整体偏轻松生活记录。", ""

    monkeypatch.setattr(toolbox_module, "_extract_video_frames", fake_extract)
    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", fake_vision)

    context = asyncio.run(analyzer.analyze(event, "[视频:手机发来的视频]", fake_action))

    assert context is not None
    prompt = context.prompt_context()
    assert "手机发来的视频" in prompt
    assert "已抽取 2 张关键帧" in prompt
    assert "人物在室内展示物品" in prompt
    assert len(vision_calls) == 1
    assert len(vision_calls[0]["prepared_images"]) == 2
    assert "按时间顺序" in str(vision_calls[0]["prompt"])


def test_toolbox_treats_mface_summary_as_context(tmp_path) -> None:
    event = {
        "message": [
            {"type": "mface", "data": {"summary": "亚托莉叉腰生气"}}
        ]
    }
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze(event, "[动画表情:亚托莉叉腰生气]"))

    assert context is not None
    assert "动画表情摘要：亚托莉叉腰生气" in context.prompt_context()
