from __future__ import annotations

from atri_webui.page import render_index


def test_voice_preview_language_sample_moves_with_the_test_panel() -> None:
    """语音试听的独立入口已撤下；语言样例文本仍由「测试」页的 TTS 面板使用。"""

    page = render_index()

    assert 'id="voicePreviewLanguage"' not in page
    assert "function useVoicePreviewLanguageSample()" in page
    assert "function useVoiceLanguageSample()" in page


def test_voice_test_panel_supports_translation_and_fast_preview() -> None:
    page = render_index()

    assert 'id="testTtsAutoTranslate"' in page
    assert 'id="testTtsStrictQuality"' in page
    assert "function translateVoiceTestText()" in page
    assert "preview_mode:$('testTtsStrictQuality').checked ? 'strict' : 'fast'" in page
    assert "const available = profiles.filter(item=>item.ready);" in page
    assert "Master, please let me stay by your side today." in page
    assert "マスター、今日もあなたのそばにいさせてください。" in page
