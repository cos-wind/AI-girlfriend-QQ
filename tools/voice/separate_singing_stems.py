from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--vocal-output", type=Path, required=True)
    parser.add_argument("--instrumental-output", type=Path, required=True)
    parser.add_argument("--harmony-output", type=Path)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument(
        "--model",
        default="UVR-MDX-NET-Inst_HQ_4.onnx",
    )
    parser.add_argument("--backend", choices=("mdx_net", "bs_roformer", "demucs"), default="mdx_net")
    parser.add_argument("--preset", choices=("quick", "standard", "extreme"), default="standard")
    parser.add_argument("--harmony-model", default="UVR-BVE-4B_SN-44100-2.pth")
    parser.add_argument("--separate-harmony", action="store_true")
    parser.add_argument("--segments-json", type=Path)
    parser.add_argument("--section-output-dir", type=Path)
    args = parser.parse_args()

    _ensure_ffmpeg_on_path()
    output_dir = args.vocal_output.resolve().parent
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="atri-sections-") as temporary:
        workspace = Path(temporary)
        separator = _load_separator(args, workspace) if args.backend != "demucs" else None
        if args.segments_json:
            sections = _load_sections(args.segments_json)
            vocal_parts: list[Path] = []
            instrumental_parts: list[Path] = []
            for index, section in enumerate(sections, start=1):
                print(
                    f"[ATRI] 正在分离第 {index}/{len(sections)} 段：{section['label']}",
                    flush=True,
                )
                source_part = workspace / f"section-{index:02d}-source.wav"
                _extract_section(
                    args.source.resolve(),
                    source_part,
                    float(section["start_seconds"]),
                    float(section["end_seconds"]),
                )
                vocal, instrumental = _separate_with_backend(
                    separator, args, source_part, workspace, index
                )
                if args.section_output_dir:
                    section_output = args.section_output_dir.resolve()
                    section_output.mkdir(parents=True, exist_ok=True)
                    vocal_copy = section_output / f"section-{index:02d}-vocal.wav"
                    instrumental_copy = section_output / f"section-{index:02d}-instrumental.wav"
                    shutil.copy2(vocal, vocal_copy)
                    shutil.copy2(instrumental, instrumental_copy)
                    vocal = vocal_copy
                    instrumental = instrumental_copy
                vocal_parts.append(vocal)
                instrumental_parts.append(instrumental)
            _concat_audio(vocal_parts, args.vocal_output.resolve())
            _concat_audio(instrumental_parts, args.instrumental_output.resolve())
        else:
            vocal, instrumental = _separate_with_backend(
                separator, args, args.source.resolve(), workspace, 0
            )
            shutil.copy2(vocal, args.vocal_output.resolve())
            shutil.copy2(instrumental, args.instrumental_output.resolve())
        if separator is not None:
            del separator
            gc.collect()
            _empty_cuda_cache()
        if args.harmony_output:
            _render_harmony(args)


def _preset_settings(name: str) -> dict[str, object]:
    return {
        "quick": {"overlap": 0.15, "segment_size": 128, "shifts": 0},
        "standard": {"overlap": 0.25, "segment_size": 256, "shifts": 1},
        "extreme": {"overlap": 0.5, "segment_size": 384, "shifts": 2},
    }[name]


def _load_separator(args: argparse.Namespace, workspace: Path):
    from audio_separator.separator import Separator

    settings = _preset_settings(args.preset)
    overlap = float(settings["overlap"])
    return_separator = Separator(
        output_dir=str(workspace),
        output_format="WAV",
        model_file_dir=str(args.model_dir.resolve()),
        sample_rate=44100,
        use_autocast=True,
        use_soundfile=True,
        log_level=logging.WARNING,
        mdx_params={
            "hop_length": 1024,
            "segment_size": int(settings["segment_size"]),
            "overlap": overlap,
            "batch_size": 1,
            "enable_denoise": args.preset == "extreme",
        },
        mdxc_params={
            "segment_size": int(settings["segment_size"]),
            "override_model_segment_size": False,
            "batch_size": 1,
            "overlap": {"quick": 2, "standard": 4, "extreme": 6}[args.preset],
            "pitch_shift": 0,
        },
    )
    print(f"[ATRI_PROGRESS] 12% 加载 {args.backend} / {args.preset} 分离模型", flush=True)
    return_separator.load_model(model_filename=args.model)
    return return_separator


def _separate_with_backend(
    separator,
    args: argparse.Namespace,
    source: Path,
    output_dir: Path,
    index: int,
) -> tuple[Path, Path]:
    if args.backend == "demucs":
        return _separate_demucs(args, source, output_dir, index)
    return _separate_one(separator, source, output_dir, index)


def _separate_demucs(
    args: argparse.Namespace,
    source: Path,
    output_dir: Path,
    index: int,
) -> tuple[Path, Path]:
    settings = _preset_settings(args.preset)
    demucs_output = output_dir / f"demucs-{index:02d}"
    command = [
        sys.executable,
        "-m",
        "demucs.separate",
        "--two-stems",
        "vocals",
        "-n",
        args.model or "htdemucs",
        "--out",
        str(demucs_output),
        "--overlap",
        str(settings["overlap"]),
        "--shifts",
        str(settings["shifts"]),
        str(source),
    ]
    print(f"[ATRI_PROGRESS] 18% Demucs 正在分离第 {max(1, index)} 段", flush=True)
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    model_dir = demucs_output / (args.model or "htdemucs") / source.stem
    return model_dir / "vocals.wav", model_dir / "no_vocals.wav"


def _render_harmony(args: argparse.Namespace) -> None:
    harmony_output = args.harmony_output.resolve()
    harmony_output.parent.mkdir(parents=True, exist_ok=True)
    if not args.separate_harmony or args.preset == "quick":
        _silence_like(args.vocal_output.resolve(), harmony_output)
        print("[ATRI_PROGRESS] 92% 快速模式保留空和声音轨", flush=True)
        return
    try:
        from audio_separator.separator import Separator

        with tempfile.TemporaryDirectory(prefix="atri-harmony-") as temporary:
            workspace = Path(temporary)
            separator = Separator(
                output_dir=str(workspace),
                output_format="WAV",
                model_file_dir=str(args.model_dir.resolve()),
                sample_rate=44100,
                use_autocast=True,
                use_soundfile=True,
                log_level=logging.WARNING,
                vr_params={
                    "batch_size": 1,
                    "window_size": 512,
                    "aggression": 5,
                    "enable_tta": args.preset == "extreme",
                    "enable_post_process": True,
                    "post_process_threshold": 0.2,
                    "high_end_process": False,
                },
            )
            print("[ATRI_PROGRESS] 82% 分离主唱与和声", flush=True)
            separator.load_model(model_filename=args.harmony_model)
            files = separator.separate(
                str(args.vocal_output.resolve()),
                # BVE is a backing-vocal extractor: its target "Vocals" stem is
                # the backing/harmony layer, while the residual is the lead.
                {"Vocals": "harmony", "Instrumental": "lead-vocal"},
            )
            paths = _resolve_output_paths(files, workspace)
            lead = _find_stem(paths, "lead-vocal")
            harmony = _find_stem(paths, "harmony")
            lead_temporary = args.vocal_output.with_suffix(".lead.tmp.wav").resolve()
            shutil.copy2(lead, lead_temporary)
            shutil.copy2(harmony, harmony_output)
            os.replace(lead_temporary, args.vocal_output.resolve())
    except Exception as exc:
        _silence_like(args.vocal_output.resolve(), harmony_output)
        print(
            f"[ATRI_PROGRESS] 92% 和声模型不可用，已安全保留空和声音轨：{exc}",
            flush=True,
        )
    finally:
        gc.collect()
        _empty_cuda_cache()


def _silence_like(source: Path, output: Path) -> None:
    import imageio_ffmpeg

    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-af",
            "volume=0",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s24le",
            str(output),
        ],
        check=True,
    )


def _empty_cuda_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _load_sections(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.resolve().read_text(encoding="utf-8-sig"))
    sections = payload.get("sections") if isinstance(payload, dict) else None
    if not isinstance(sections, list) or not 3 <= len(sections) <= 5:
        raise ValueError("乐理分段必须包含 3 到 5 段")
    return sections


def _separate_one(separator, source: Path, output_dir: Path, index: int) -> tuple[Path, Path]:
    prefix = f"section-{index:02d}" if index else "separated"
    vocal_name = f"{prefix}-vocal"
    instrumental_name = f"{prefix}-instrumental"
    files = separator.separate(
        str(source),
        {"Vocals": vocal_name, "Instrumental": instrumental_name},
    )
    resolved = _resolve_output_paths(files, output_dir)
    return _find_stem(resolved, vocal_name), _find_stem(resolved, instrumental_name)


def _extract_section(source: Path, output: Path, start: float, end: float) -> None:
    import imageio_ffmpeg

    duration = max(0.1, end - start)
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(output),
        ],
        check=True,
    )


def _concat_audio(parts: list[Path], output: Path) -> None:
    import imageio_ffmpeg

    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y"]
    for part in parts:
        command.extend(("-i", str(part)))
    inputs = "".join(f"[{index}:a]" for index in range(len(parts)))
    command.extend(
        (
            "-filter_complex",
            f"{inputs}concat=n={len(parts)}:v=0:a=1[out]",
            "-map",
            "[out]",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(output),
        )
    )
    subprocess.run(command, check=True)


def _find_stem(paths: list[Path], name: str) -> Path:
    expected = name.casefold()
    for path in paths:
        if expected in path.stem.casefold() and path.is_file():
            return path
    raise FileNotFoundError(f"人声分离没有生成 {name}：{paths}")


def _resolve_output_paths(files: list[str], output_dir: Path) -> list[Path]:
    resolved: list[Path] = []
    for item in files:
        path = Path(item).expanduser()
        resolved.append((path if path.is_absolute() else output_dir / path).resolve())
    return resolved


def _ensure_ffmpeg_on_path() -> None:
    import imageio_ffmpeg

    source = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    runtime_bin = Path(sys.executable).resolve().parent
    alias = runtime_bin / "ffmpeg.exe"
    if not alias.is_file() or alias.stat().st_size != source.stat().st_size:
        shutil.copy2(source, alias)
    os.environ["PATH"] = f"{runtime_bin}{os.pathsep}{os.environ.get('PATH', '')}"


if __name__ == "__main__":
    main()
