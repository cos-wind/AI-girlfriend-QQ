from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
VOICE_TOOLS = ROOT / "tools" / "voice"
sys.path.insert(0, str(VOICE_TOOLS))

from singing_audio_engineering import (  # noqa: E402
    _moving_average,
    _rough_pitch,
    apply_expression,
    assemble_contextual_parts,
    build_phrase_plan,
    patch_selected_range,
    quality_report,
)


def test_phrase_plan_uses_breath_boundaries_and_two_to_four_seconds_context() -> None:
    sample_rate = 100
    audio = np.ones(10000, dtype=np.float32) * 0.2
    for second in (20, 40, 60, 80):
        audio[second * sample_rate : second * sample_rate + 40] = 0
    analysis = {
        "duration_seconds": 100,
        "sections": [
            {"index": index + 1, "start_seconds": index * 20, "end_seconds": (index + 1) * 20}
            for index in range(5)
        ],
    }

    plan = build_phrase_plan(audio, sample_rate, analysis, context_seconds=3)

    assert 3 <= len(plan["render_groups"]) <= 5
    assert len(plan["phrases"]) >= 5
    assert plan["f0_engine"] == "rmvpe"
    assert all(2 <= item["context_seconds"] <= 4 for item in plan["render_groups"])
    assert any(item["boundary_reason"] == "breath" for item in plan["phrases"][1:])


def test_overlap_add_has_no_hard_jump_between_contextual_parts() -> None:
    sample_rate = 100
    plan = {
        "duration_seconds": 10,
        "render_groups": [
            {"start_seconds": 0, "end_seconds": 5, "context_start": 0, "context_end": 7},
            {"start_seconds": 5, "end_seconds": 10, "context_start": 3, "context_end": 10},
        ],
    }
    left = np.ones(700, dtype=np.float32) * 0.25
    right = np.ones(700, dtype=np.float32) * 0.5

    output = assemble_contextual_parts([left, right], sample_rate, plan)

    assert output.shape == (1000,)
    assert np.isfinite(output).all()
    assert np.max(np.abs(np.diff(output[450:550]))) < 0.02


def test_patch_changes_only_selected_range_and_keeps_rest_bit_identical() -> None:
    sample_rate = 100
    base = np.zeros(1000, dtype=np.float32)
    replacement_context = np.ones(500, dtype=np.float32)

    output = patch_selected_range(
        base,
        replacement_context,
        sample_rate,
        start_seconds=4,
        end_seconds=6,
        context_start=2,
    )

    np.testing.assert_array_equal(output[:400], base[:400])
    np.testing.assert_array_equal(output[600:], base[600:])
    assert output[450:550].mean() > 0.95


def test_patch_crossfades_toward_the_unchanged_audio_at_both_edges() -> None:
    sample_rate = 1000
    base = np.full(3000, -0.4, dtype=np.float32)
    replacement_context = np.full(2000, 0.4, dtype=np.float32)

    output = patch_selected_range(
        base,
        replacement_context,
        sample_rate,
        start_seconds=1,
        end_seconds=2,
        context_start=0.5,
    )

    assert abs(float(output[1000] - base[999])) < 1e-5
    assert abs(float(output[1999] - base[2000])) < 1e-5
    assert output[1500] > 0.35


def test_expression_processing_preserves_shape_and_finite_values() -> None:
    sample_rate = 16000
    time = np.arange(sample_rate, dtype=np.float32) / sample_rate
    converted = (0.15 * np.sin(2 * np.pi * 220 * time)).astype(np.float32)
    source = converted.copy()

    output = apply_expression(
        converted,
        source,
        sample_rate,
        {
            "breathiness": 0.2,
            "vibrato": 0.2,
            "articulation": 0.7,
            "formant_shift": 0.7,
        },
    )

    assert output.shape == converted.shape
    assert np.isfinite(output).all()
    assert np.max(np.abs(output)) <= 1.0


def test_long_envelope_uses_linear_time_moving_average() -> None:
    audio = np.linspace(-0.2, 0.2, 200_000, dtype=np.float32)

    with patch.object(np, "convolve", side_effect=AssertionError("full convolution")):
        smoothed = _moving_average(audio, 882)

    assert smoothed.shape == audio.shape
    assert np.isfinite(smoothed).all()


def test_quality_report_detects_clipping_silence_and_seam_click() -> None:
    sample_rate = 1000
    source = np.ones(4000, dtype=np.float32) * 0.2
    converted = source.copy()
    converted[1000:2000] = 0
    converted[2500] = 1.0

    report = quality_report(source, converted, sample_rate, seam_times=[2.5])

    checks = {item["id"]: item for item in report["checks"]}
    assert checks["abnormal_silence"]["passed"] is False
    assert checks["clipping"]["passed"] is False
    assert checks["seam_click"]["passed"] is False
    json.dumps(report)


def test_pitch_check_uses_bounded_fft_autocorrelation() -> None:
    sample_rate = 44100
    time = np.arange(sample_rate * 3, dtype=np.float32) / sample_rate
    signal = (0.2 * np.sin(2 * np.pi * 220 * time)).astype(np.float32)

    with patch.object(np, "correlate", side_effect=AssertionError("quadratic autocorrelation")):
        pitch = _rough_pitch(signal, sample_rate)

    assert pitch is not None
    assert abs(pitch - 220.0) < 5.0
