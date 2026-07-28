import asyncio
import http.server
import json
import threading
import zipfile
from dataclasses import replace
from pathlib import Path

from atri_qq_bot.config import BotConfig
from atri_qq_bot.persona import AtriReplyEngine
import atri_qq_bot.toolbox as toolbox_module
from atri_qq_bot.toolbox import ToolAnalysisResult, ToolAnalyzer


def _config(tmp_path: Path) -> BotConfig:
    return BotConfig(
        bot_qq=111111111,
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
    doc.write_text("浠婂ぉ鐮旂┒涓婚锛氱潯鐪犱笉瓒充細褰卞搷娉ㄦ剰鍔涖€傚缓璁厛琛ヨ锛屽啀鍋氶珮寮哄害浠诲姟銆?, encoding="utf-8")
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"甯垜鎬荤粨杩欎釜鏂囨。 {doc}"))
    engine = AtriReplyEngine(_config(tmp_path))
    reply = asyncio.run(
        engine.reply("private:10001", f"甯垜鎬荤粨杩欎釜鏂囨。 {doc}", tool_context=context)
    )

    assert context is not None
    assert context.category == "鐢熸椿瀛︽湳鐮旂┒"
    assert "鐫＄湢涓嶈冻" in context.prompt_context()
    assert "鍥炲澶辫触" in reply
    assert "鏈娇鐢ㄦ湰鍦板唴瀹规ā鏉? in reply


def test_toolbox_reads_csv_as_research_data(tmp_path) -> None:
    csv = tmp_path / "score.csv"
    csv.write_text("name,score\nA,91\nB,82\n", encoding="utf-8")
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"鍒嗘瀽琛ㄦ牸鏁版嵁 {csv}"))

    assert context is not None
    assert context.category == "鐢熸椿瀛︽湳鐮旂┒"
    assert "2 琛屾暟鎹? in context.prompt_context()
    assert "name銆乻core" in context.prompt_context()


def test_toolbox_reads_docx_without_external_dependency(tmp_path) -> None:
    docx = tmp_path / "report.docx"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>鏍稿績缁撹鏄厛鍋氬皬鏍锋湰楠岃瘉銆?/w:t></w:r></w:p></w:body>"
                "</w:document>"
            ),
        )
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"鎬荤粨鏂囨。 {docx}"))

    assert context is not None
    assert "鏍稿績缁撹" in context.prompt_context()


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
            xml_prefix + "<w:body><w:p><w:r><w:t>姝ｆ枃缁撹锛氬厛鍋氱敤鎴疯璋堛€?/w:t></w:r></w:p></w:body>" + xml_suffix,
        )
        archive.writestr(
            "word/header1.xml",
            xml_prefix + "<w:body><w:p><w:r><w:t>椤电湁椤圭洰锛欰TRI璋冪爺銆?/w:t></w:r></w:p></w:body>" + xml_suffix,
        )
        archive.writestr(
            "word/footer1.xml",
            xml_prefix + "<w:body><w:p><w:r><w:t>椤佃剼鐗堟湰锛歏2銆?/w:t></w:r></w:p></w:body>" + xml_suffix,
        )
        archive.writestr(
            "word/comments.xml",
            xml_prefix + "<w:body><w:p><w:r><w:t>鎵规敞锛氭牱鏈噺闇€瑕佹墿澶с€?/w:t></w:r></w:p></w:body>" + xml_suffix,
        )
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"娣卞害鎬荤粨杩欎釜鏂囨。 {docx}"))

    assert context is not None
    prompt = context.prompt_context()
    assert "姝ｆ枃缁撹" in prompt
    assert "椤电湁椤圭洰" in prompt
    assert "椤佃剼鐗堟湰" in prompt
    assert "鏍锋湰閲忛渶瑕佹墿澶? in prompt


def test_toolbox_reads_xlsx_without_external_dependency(tmp_path) -> None:
    xlsx = tmp_path / "data.xlsx"
    with zipfile.ZipFile(xlsx, "w") as archive:
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<sheetData>"
                '<row r="1"><c r="A1" t="inlineStr"><is><t>鏃ユ湡</t></is></c>'
                '<c r="B1" t="inlineStr"><is><t>閿€閲?/t></is></c></row>'
                '<row r="2"><c r="A2" t="inlineStr"><is><t>鍛ㄤ竴</t></is></c><c r="B2"><v>12</v></c></row>'
                "</sheetData></worksheet>"
            ),
        )
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"鍒嗘瀽琛ㄦ牸 {xlsx}"))

    assert context is not None
    assert "Excel 琛ㄦ牸" in context.prompt_context()
    assert "鏃ユ湡銆侀攢閲? in context.prompt_context()


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
                '<sheet name="閿€閲? sheetId="1" r:id="rId1"/>'
                '<sheet name="鎴愭湰" sheetId="2" r:id="rId2"/>'
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
                '<row r="1"><c r="A1" t="inlineStr"><is><t>鍟嗗搧</t></is></c><c r="B1" t="inlineStr"><is><t>閿€閲?/t></is></c></row>'
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
                '<row r="1"><c r="A1" t="inlineStr"><is><t>鍟嗗搧</t></is></c><c r="B1" t="inlineStr"><is><t>鎴愭湰</t></is></c></row>'
                '<row r="2"><c r="A2" t="inlineStr"><is><t>A</t></is></c><c r="B2"><v>3</v></c></row>'
                '<row r="3"><c r="A3" t="inlineStr"><is><t>B</t></is></c><c r="B3"><v>8</v></c></row>'
                "</sheetData></worksheet>"
            ),
        )
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"鍒嗘瀽琛ㄦ牸鏁版嵁 {xlsx}"))

    assert context is not None
    prompt = context.prompt_context()
    assert "璇诲彇鍒?2 涓伐浣滆〃" in prompt
    assert "宸ヤ綔琛?閿€閲? in prompt
    assert "宸ヤ綔琛?鎴愭湰" in prompt
    assert "閿€閲?count=2 min=10 max=20 avg=15" in prompt
    assert "鎴愭湰 count=2 min=3 max=8 avg=5.50" in prompt


def test_toolbox_reads_csv_quoted_commas_and_numeric_summary(tmp_path) -> None:
    csv_file = tmp_path / "quoted.csv"
    csv_file.write_text('name,comment,score\nA,"鍠滄,浣嗘湁鐐硅吹",91\nB,"绋冲畾",82\n', encoding="utf-8")
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"鍒嗘瀽杩欎釜琛ㄦ牸 {csv_file}"))

    assert context is not None
    prompt = context.prompt_context()
    assert "name銆乧omment銆乻core" in prompt
    assert "鍠滄,浣嗘湁鐐硅吹" in prompt
    assert "score count=2 min=82 max=91 avg=86.50" in prompt


def test_toolbox_reads_local_png_metadata_when_user_asks_to_analyze_image(tmp_path) -> None:
    png = tmp_path / "shot.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x02\x00\x00\x00\x03"
        b"\x08\x06\x00\x00\x00\x00\x00\x00\x00"
    )
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze({"message": ""}, f"鍒嗘瀽鍥剧墖 {png}"))

    assert context is not None
    assert context.category == "鏃ュ父鐢熸椿涔愯叮"
    assert "2x3" in context.prompt_context()
    assert "涓嶄贡缂? in context.prompt_context() or "鑷嗘祴" in context.prompt_context()


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
        return "鐢婚潰鍍忔竻鏅ㄦ埧闂存埅鍥撅紝鑹茶皟骞插噣锛屽彲浠ュじ涓€鍙ュ緢鏈夌敓娲绘劅銆?, ""

    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", fake_vision)

    context = asyncio.run(analyzer.analyze({"message": ""}, f"璇勪环杩欏紶鍥?{png}"))

    assert context is not None
    prompt = context.prompt_context()
    assert "鍥剧墖鍐呭鍒嗘瀽" in prompt
    assert "娓呮櫒鎴块棿鎴浘" in prompt
    assert "鐢熸椿鎰? in prompt
    assert "浼樺厛鍥寸粫褰撳墠鐢婚潰鎴栬〃鎯呮儏缁洖澶? in prompt


def test_toolbox_routes_mface_image_to_sticker_emotion_analysis(monkeypatch, tmp_path) -> None:
    png = tmp_path / "atri_mface.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x30\x00\x00\x00\x30"
        b"\x08\x06\x00\x00\x00\x00\x00\x00\x00"
    )
    event = {"message": [{"type": "mface", "data": {"summary": "浜氭墭鑾夊弶鑵扮敓姘?, "file": str(png)}}]}
    analyzer = ToolAnalyzer(_config(tmp_path))

    async def fake_vision(data: bytes, source: str, prompt: str | None = None) -> tuple[str, str]:
        assert "琛ㄦ儏鍖?姊楀浘/鍔ㄧ敾琛ㄦ儏" in (prompt or "")
        return "绫诲瀷锛氳〃鎯呭寘锛涙儏缁細鐢熸皵浣嗗甫鐐规拻濞囷紱鐢婚潰锛氳鑹插弶鑵帮紱閫傚悎鎬庝箞鎺ヨ瘽锛氬彲浠ラ『鐫€鍝勫ス銆?, ""

    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", fake_vision)

    context = asyncio.run(analyzer.analyze(event, "[鍔ㄧ敾琛ㄦ儏:浜氭墭鑾夊弶鑵扮敓姘擼"))

    assert context is not None
    prompt = context.prompt_context()
    assert "琛ㄦ儏鍖呬俊鎭? in prompt
    assert "琛ㄦ儏鍖呮儏缁垎鏋? in prompt
    assert "鐢熸皵浣嗗甫鐐规拻濞? in prompt


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
            "<think>鍏堝垎鏋愪竴涓?/think>\n"
            "analysis: hidden tool process\n"
            "QWERTY12345:/==++++\n"
            "绫诲瀷锛氭櫘閫氬浘鐗囷紱涓讳綋/鍦烘櫙锛氭父鎴忕晫闈㈡埅鍥撅紱鍏抽敭鏂囧瓧鎴朥I锛氳兘鐪嬪埌瑙掕壊鍜屾寜閽€?
        ), ""

    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", fake_vision)

    context = asyncio.run(analyzer.analyze({"message": ""}, f"鍒嗘瀽杩欏紶鍥?{png}"))

    assert context is not None
    prompt = context.prompt_context()
    assert "鍥剧墖鍐呭鍒嗘瀽" in prompt
    assert "娓告垙鐣岄潰鎴浘" in prompt
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
        context = asyncio.run(analyzer.analyze(event, "杩欏紶鎬庝箞鏍?))
    finally:
        server.shutdown()
        __import__("os").chdir(old_cwd)

    assert context is not None
    assert "6x7" in context.prompt_context()


def test_toolbox_fetches_webpage_from_local_server(tmp_path) -> None:
    served = tmp_path / "served"
    served.mkdir()
    (served / "index.html").write_text(
        "<html><head><title>鐮旂┒椤甸潰</title><meta name='description' content='杩欐槸绠€浠?></head>"
        "<body><main>姝ｆ枃璇翠粖澶╃殑鏁版嵁闇€瑕佸厛鏍稿鏉ユ簮锛屽啀姣旇緝瓒嬪娍銆?/main></body></html>",
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
        context = asyncio.run(analyzer.analyze({"message": ""}, f"鏌ヨ鏉冨▉璧勬枡 {url}"))
    finally:
        server.shutdown()
        __import__("os").chdir(old_cwd)

    assert context is not None
    assert "鐮旂┒椤甸潰" in context.prompt_context()
    assert "鏍稿鏉ユ簮" in context.prompt_context()


def test_toolbox_recognizes_bilibili_material_from_api(monkeypatch, tmp_path) -> None:
    analyzer = ToolAnalyzer(_config(tmp_path))

    async def fake_fetch(url: str) -> tuple[bytes, str, str]:
        if "x/web-interface/view" in url:
            return (
                json.dumps(
                    {
                        "data": {
                            "title": "楂樿兘鏁存椿瑙嗛",
                            "owner": {"name": "UP涓籄"},
                            "tname": "鎼炵瑧",
                            "desc": "杩欎釜瑙嗛涓绘墦鐢熸椿鏁存椿銆?,
                            "stat": {"view": 100, "like": 20},
                            "pages": [{"part": "姝ｇ墖", "cid": 123}],
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
        analyzer.analyze({"message": ""}, "鍒嗘瀽杩欎釜b绔欒棰?https://www.bilibili.com/video/BV1abcabcabc")
    )

    assert context is not None
    assert context.category == "鏃ュ父鐢熸椿涔愯叮"
    assert "鎶借薄鏈夎叮" in context.prompt_context()
    assert "楂樿兘鏁存椿瑙嗛" in context.prompt_context()
    assert "UP涓籄" in context.prompt_context()


def test_toolbox_reads_mobile_file_segment_with_url(tmp_path) -> None:
    served = tmp_path / "served_file"
    served.mkdir()
    (served / "mobile-note.txt").write_text("绉诲姩绔洿鍙戞枃浠跺唴瀹癸細浠婂ぉ瑕佸厛瀹屾垚椤圭洰璋冭瘯銆?, encoding="utf-8")

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
                {"type": "text", "data": {"text": "甯垜鎬荤粨杩欎釜鏂囦欢"}},
                {"type": "file", "data": {"name": "mobile-note.txt", "url": url}},
            ]
        }
        analyzer = ToolAnalyzer(_config(tmp_path))
        context = asyncio.run(analyzer.analyze(event, "甯垜鎬荤粨杩欎釜鏂囦欢[鏂囦欢:mobile-note.txt]"))
    finally:
        server.shutdown()
        __import__("os").chdir(old_cwd)

    assert context is not None
    assert context.category == "鐢熸椿瀛︽湳鐮旂┒"
    assert "绉诲姩绔洿鍙戞枃浠跺唴瀹? in context.prompt_context()
    assert "椤圭洰璋冭瘯" in context.prompt_context()


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
                "<w:body><w:p><w:r><w:t>鏃犲悗缂€閾炬帴閲岀殑DOCX姝ｆ枃銆?/w:t></w:r></w:p></w:body>"
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
                {"type": "file", "data": {"name": "鎵嬫満鏂囨。.docx", "url": url}},
            ]
        }
        analyzer = ToolAnalyzer(_config(tmp_path))
        context = asyncio.run(analyzer.analyze(event, "[鏂囦欢:鎵嬫満鏂囨。.docx]"))
    finally:
        server.shutdown()
        __import__("os").chdir(old_cwd)

    assert context is not None
    assert "鏃犲悗缂€閾炬帴閲岀殑DOCX姝ｆ枃" in context.prompt_context()


def test_toolbox_reads_mobile_file_segment_through_onebot_action(monkeypatch, tmp_path) -> None:
    served = tmp_path / "served_action_file"
    served.mkdir()
    (served / "action-note.txt").write_text("閫氳繃 NapCat file_id 鍙栧緱鐨勬鏂囥€?, encoding="utf-8")

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

        context = asyncio.run(analyzer.analyze(event, "[鏂囦欢:action-note.txt]", fake_action))
    finally:
        server.shutdown()
        __import__("os").chdir(old_cwd)

    assert context is not None
    assert "閫氳繃 NapCat file_id" in context.prompt_context()


def test_toolbox_reads_bilibili_mobile_share_card(monkeypatch, tmp_path) -> None:
    analyzer = ToolAnalyzer(_config(tmp_path))

    async def fake_fetch(url: str) -> tuple[bytes, str, str]:
        if "x/web-interface/view" in url:
            return (
                json.dumps(
                    {
                        "data": {
                            "title": "瀚夊浣夸汉闈㈢洰鍏ㄩ潪",
                            "owner": {"name": "缃楃繑璇村垜娉?},
                            "tname": "鐭ヨ瘑",
                            "desc": "濡備綍闈㈠瀚夊鐨勫叕寮€绠€浠嬨€?,
                            "stat": {"view": 200, "like": 30},
                            "pages": [{"part": "姝ｇ墖", "cid": 456}],
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
                "title": "缃楃繑锛氬浣曢潰瀵瑰珘濡?,
                "qqdocurl": "https://www.bilibili.com/video/BV1abcabcabc",
            }
        }
    }
    event = {"message": [{"type": "json", "data": {"data": json.dumps(share_payload, ensure_ascii=False)}}]}

    context = asyncio.run(analyzer.analyze(event, "[鍒嗕韩:缃楃繑锛氬浣曢潰瀵瑰珘濡抅"))

    assert context is not None
    assert context.category == "鏃ュ父鐢熸椿涔愯叮"
    assert "瀚夊浣夸汉闈㈢洰鍏ㄩ潪" in context.prompt_context()
    assert "缃楃繑璇村垜娉? in context.prompt_context()


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
                {"type": "video", "data": {"title": "鎵嬫満鍙戞潵鐨勮棰?}},
            ]
        }
        analyzer = ToolAnalyzer(_config(tmp_path))
        context = asyncio.run(analyzer.analyze(event, "[琛ㄦ儏鍖?鍥剧墖:shot.png][瑙嗛:鎵嬫満鍙戞潵鐨勮棰慮"))
    finally:
        server.shutdown()
        __import__("os").chdir(old_cwd)

    assert context is not None
    prompt = context.prompt_context()
    assert "4x5" in prompt
    assert "鎵嬫満鍙戞潵鐨勮棰? in prompt
    assert "涓嶄細鑷嗘祴鍥剧墖閲屽叿浣撶敾闈? in prompt
    assert "鏆備笉鑷姩涓嬭浇鍜岃В鏋愮敾闈? in prompt


def test_toolbox_marks_title_only_video_as_metadata_only(tmp_path) -> None:
    event = {
        "message": [
            {"type": "video", "data": {"title": "鎵嬫満鍙戞潵鐨勮棰?}}
        ]
    }
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze(event, "[瑙嗛:鎵嬫満鍙戞潵鐨勮棰慮"))

    assert context is not None
    assert context.read_level == "metadata_only"
    prompt = context.prompt_context()
    assert "鍙鍒版爣棰? in prompt
    assert "绂佹璇粹€滄垜鐪嬪畬浜嗚棰戔€? in prompt
    assert "鎵嬫満鍙戞潵鐨勮棰? in prompt


def test_metadata_only_result_detects_claims_about_unread_content() -> None:
    context = ToolAnalysisResult(
        category="濞变箰鍚愭Ы",
        style="casual",
        findings=["鍙鍒版爣棰橈細鎵嬫満鍙戞潵鐨勮棰?],
        limitations=["娌℃湁璇诲彇瑙嗛鐢婚潰鎴栧０闊?],
        read_level="metadata_only",
    )

    assert context.needs_grounding_repair("鎴戠偣杩涘幓鐪嬩簡锛岃棰戦噷璁插緱鎸烘竻妤?)
    assert context.needs_grounding_repair("杩欎釜鏃嬪緥鍚捣鏉ュ緢涓婂ご")
    assert not context.needs_grounding_repair("鎴戣繖閲屽彧璇诲埌浜嗘爣棰橈紝鏆傛椂鍒ゆ柇涓嶄簡鐢婚潰鍐呭")


def test_normal_reply_repairs_material_claim_once(monkeypatch, tmp_path) -> None:
    config = replace(_config(tmp_path), openai_api_key="test-key")
    engine = AtriReplyEngine(config)
    context = ToolAnalysisResult(
        category="濞变箰鍚愭Ы",
        style="casual",
        findings=["鍙鍒版爣棰橈細鎵嬫満鍙戞潵鐨勮棰?],
        limitations=["娌℃湁璇诲彇瑙嗛鐢婚潰鎴栧０闊?],
        read_level="metadata_only",
    )
    replies = iter(
        [
            "鎴戠偣杩涘幓鐪嬩簡锛岃棰戦噷鐨勬棆寰嬫尯涓婂ご銆?,
            "鎴戣繖閲屽彧璇诲埌浜嗘爣棰橈紝杩樺垽鏂笉浜嗙敾闈㈠拰澹伴煶銆備綘鏇存兂鑱婂畠鐨勫摢涓€閮ㄥ垎锛?,
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
            "浣犵湅鐪嬭繖涓棰?,
            tool_context=context,
        )
    )

    assert len(calls) == 2
    assert calls[1]["allow_reply_voice"] is False
    assert "鍙鍒颁簡鏍囬" in reply
    assert not context.needs_grounding_repair(reply)


def test_toolbox_reads_mobile_video_through_onebot_action(monkeypatch, tmp_path) -> None:
    video_file = tmp_path / "clip.mp4"
    video_file.write_bytes(b"fake-video")
    event = {
        "message": [
            {"type": "video", "data": {"title": "鎵嬫満鍙戞潵鐨勮棰?, "file_id": "video-123"}}
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
        return "鐪嬪埌浜虹墿鍦ㄥ鍐呭睍绀虹墿鍝侊紝鏁翠綋鍋忚交鏉剧敓娲昏褰曘€?, ""

    monkeypatch.setattr(toolbox_module, "_extract_video_frames", fake_extract)
    monkeypatch.setattr(analyzer, "_analyze_image_with_vision", fake_vision)

    context = asyncio.run(analyzer.analyze(event, "[瑙嗛:鎵嬫満鍙戞潵鐨勮棰慮", fake_action))

    assert context is not None
    prompt = context.prompt_context()
    assert "鎵嬫満鍙戞潵鐨勮棰? in prompt
    assert "宸叉娊鍙?2 寮犲叧閿抚" in prompt
    assert "浜虹墿鍦ㄥ鍐呭睍绀虹墿鍝? in prompt


def test_toolbox_treats_mface_summary_as_context(tmp_path) -> None:
    event = {
        "message": [
            {"type": "mface", "data": {"summary": "浜氭墭鑾夊弶鑵扮敓姘?}}
        ]
    }
    analyzer = ToolAnalyzer(_config(tmp_path))

    context = asyncio.run(analyzer.analyze(event, "[鍔ㄧ敾琛ㄦ儏:浜氭墭鑾夊弶鑵扮敓姘擼"))

    assert context is not None
    assert "鍔ㄧ敾琛ㄦ儏鎽樿锛氫簹鎵樿帀鍙夎叞鐢熸皵" in context.prompt_context()
