from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--vocal-output", type=Path, required=True)
    parser.add_argument("--instrumental-output", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument(
        "--model",
        default="UVR-MDX-NET-Inst_HQ_4.onnx",
    )
    args = parser.parse_args()

    _ensure_ffmpeg_on_path()
    from audio_separator.separator import Separator

    output_dir = args.vocal_output.resolve().parent
    output_dir.mkdir(parents=True, exist_ok=True)
    separator = Separator(
        output_dir=str(output_dir),
        output_format="WAV",
        model_file_dir=str(args.model_dir.resolve()),
        sample_rate=44100,
        use_autocast=True,
    )
    separator.load_model(model_filename=args.model)
    files = separator.separate(
        str(args.source.resolve()),
        {
            "Vocals": "separated-vocal",
            "Instrumental": "separated-instrumental",
        },
    )
    resolved = _resolve_output_paths(files, output_dir)
    vocal = _find_stem(resolved, "separated-vocal")
    instrumental = _find_stem(resolved, "separated-instrumental")
    shutil.copy2(vocal, args.vocal_output.resolve())
    shutil.copy2(instrumental, args.instrumental_output.resolve())


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
