from __future__ import annotations

from atri_webui.page import render_index


def test_voice_preview_language_switches_to_matching_sample_text() -> None:
    page = render_index()

    assert 'id="voicePreviewLanguage" onchange="useVoicePreviewLanguageSample()"' in page
    assert "function useVoicePreviewLanguageSample()" in page


def test_voice_test_panel_supports_translation_and_fast_preview() -> None:
    page = render_index()

    assert 'id="testTtsAutoTranslate"' in page
    assert 'id="testTtsStrictQuality"' in page
    assert "function translateVoiceTestText()" in page
    assert "preview_mode:$('testTtsStrictQuality').checked ? 'strict' : 'fast'" in page
    assert "const available = profiles.filter(item=>item.ready);" in page
    assert "Master, please let me stay by your side today." in page
    assert "マスター、今日もあなたのそばにいさせてください。" in page
