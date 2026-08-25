from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
VOICE_TOOLS = ROOT / "tools" / "voice"
sys.path.insert(0, str(VOICE_TOOLS))

from seed_vc_singing_adapter import select_reference_excerpt  # noqa: E402


def test_reference_excerpt_is_short_active_and_avoids_silent_intro() -> None:
    sample_rate = 1000
    reference = np.zeros(sample_rate * 30, dtype=np.float32)
    time = np.arange(sample_rate * 15, dtype=np.float32) / sample_rate
    reference[sample_rate * 10 : sample_rate * 25] = 0.2 * np.sin(2 * np.pi * 220 * time)

    excerpt, start_seconds = select_reference_excerpt(reference, sample_rate, seconds=8)

    assert len(excerpt) == sample_rate * 8
    assert 9.5 <= start_seconds <= 16.5
    assert np.sqrt(np.mean(excerpt**2)) > 0.1


def test_adapter_keeps_reference_prompt_out_of_model_output_directory() -> None:
    source = (VOICE_TOOLS / "seed_vc_singing_adapter.py").read_text(encoding="utf-8")

    assert 'output_dir / "prompt" / "atri-reference-prompt.wav"' in source
    assert "output_dir.glob(\"*.wav\")" in source
