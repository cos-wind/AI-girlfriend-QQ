import asyncio
import http.server
import json
import threading
import zipfile
from pathlib import Path

from atri_qq_bot.config import BotConfig
from atri_qq_bot.persona import AtriReplyEngine
import atri_qq_bot.toolbox as toolbox_module
from atri_qq_bot.toolbox import ToolAnalyzer


def _config(tmp_path: Path) -> BotConfig:
    return BotConfig(
        bot_qq=3380609082,
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


def test_toolbox_reads_text_document_and_persona_uses_fallback(tmp_path) -> None:
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
    assert "严谨" in reply
    assert "睡眠不足" in reply


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

    async def fake_vision(data: bytes, source: str, prompt: str | None = None) -> tuple[str, str]:
        return "看到人物在室内展示物品，整体偏轻松生活记录。", ""

    monkeypatch.setattr(toolbox_module, "_extract_video_frames", fake_extract)
    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", fake_vision)

    context = asyncio.run(analyzer.analyze(event, "[视频:手机发来的视频]", fake_action))

    assert context is not None
    prompt = context.prompt_context()
    assert "手机发来的视频" in prompt
    assert "已抽取 2 张关键帧" in prompt
    assert "人物在室内展示物品" in prompt


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
