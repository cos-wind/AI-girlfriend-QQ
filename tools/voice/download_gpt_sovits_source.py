from __future__ import annotations

import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


REVISION = "d523079fc05d9a8028d6085bffe4a2757c32abb6"
ARCHIVE_URL = f"https://github.com/RVC-Boss/GPT-SoVITS/archive/{REVISION}.zip"
DEFAULT_DESTINATION = Path(__file__).resolve().parents[2] / "data" / "runtime" / "gpt-sovits" / "source"


def main() -> None:
    destination = DEFAULT_DESTINATION
    revision_file = destination / ".atri-source-revision"
    if revision_file.is_file() and revision_file.read_text(encoding="ascii").strip() == REVISION:
        print(f"[verified] GPT-SoVITS {REVISION}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="atri-gpt-sovits-") as temp_dir:
        archive = Path(temp_dir) / "source.zip"
        request = urllib.request.Request(ARCHIVE_URL, headers={"User-Agent": "AI-ATRI-voice-setup/1.0"})
        print(f"[download] {ARCHIVE_URL}", flush=True)
        with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)

        with zipfile.ZipFile(archive) as bundle:
            roots = {name.split("/", 1)[0] for name in bundle.namelist() if "/" in name}
            if len(roots) != 1:
                raise RuntimeError("Unexpected GPT-SoVITS archive structure")
            bundle.extractall(temp_dir)

        extracted = Path(temp_dir) / roots.pop()
        if not (extracted / "api_v2.py").is_file():
            raise RuntimeError("GPT-SoVITS api_v2.py is missing from the official archive")
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(extracted), destination)
        revision_file.write_text(REVISION + "\n", encoding="ascii")
        print(f"[installed] {destination}")


if __name__ == "__main__":
    main()
