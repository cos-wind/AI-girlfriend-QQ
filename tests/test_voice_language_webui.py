from __future__ import annotations

from atri_webui.page import render_index


def test_voice_preview_language_switches_to_matching_sample_text() -> None:
    page = render_index()

    assert 'id="voicePreviewLanguage" onchange="useVoicePreviewLanguageSample()"' in page
    assert "function useVoicePreviewLanguageSample()" in page
    assert "Master, please let me stay by your side today." in page
    assert "マスター、今日もあなたのそばにいさせてください。" in page

