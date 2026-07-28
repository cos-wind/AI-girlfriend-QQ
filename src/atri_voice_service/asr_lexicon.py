from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_ENTRIES = (
    {"term": "亚托莉", "aliases": ["亚托利", "亚托丽", "阿托莉"]},
    {"term": "夏生", "aliases": ["夏声", "下生"]},
    {"term": "萝卜子", "aliases": ["萝卜仔"]},
    {"term": "GPT-SoVITS", "aliases": ["GPT SoVITS", "GPT-Sovits"]},
    {"term": "NapCat", "aliases": ["Nap Cat"]},
)


@dataclass(frozen=True)
class LexiconEntry:
    term: str
    aliases: tuple[str, ...]


class AsrLexicon:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._mtime_ns: int | None = None
        self._entries: tuple[LexiconEntry, ...] = ()

    @property
    def entries(self) -> tuple[LexiconEntry, ...]:
        self._reload_if_changed()
        return self._entries

    def terms(self) -> list[str]:
        return [entry.term for entry in self.entries]

    def correct(self, text: str) -> str:
        corrected = str(text or "")
        for entry in self.entries:
            for alias in sorted(entry.aliases, key=len, reverse=True):
                if not alias or alias == entry.term:
                    continue
                flags = re.IGNORECASE if alias.isascii() else 0
                corrected = re.sub(re.escape(alias), entry.term, corrected, flags=flags)
        return corrected

    def _reload_if_changed(self) -> None:
        if not self.path.is_file():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            save_lexicon(self.path, list(DEFAULT_ENTRIES))
        mtime_ns = self.path.stat().st_mtime_ns
        if self._mtime_ns == mtime_ns:
            return
        self._entries = tuple(parse_lexicon(self.path))
        self._mtime_ns = mtime_ns


def load_lexicon_payload(path: Path) -> dict[str, Any]:
    lexicon = AsrLexicon(path)
    return {
        "version": 1,
        "entries": [
            {"term": entry.term, "aliases": list(entry.aliases)} for entry in lexicon.entries
        ],
    }


def save_lexicon(path: Path, entries: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = _normalized_entries(entries)
    payload = {"version": 1, "entries": normalized}
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return payload


def parse_lexicon(path: Path) -> list[LexiconEntry]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"语音专有词配置无效：{exc}") from exc
    raw_entries = payload.get("entries", []) if isinstance(payload, dict) else []
    return [
        LexiconEntry(str(item["term"]), tuple(str(alias) for alias in item["aliases"]))
        for item in _normalized_entries(raw_entries)
    ]


def _normalized_entries(entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise ValueError("语音专有词必须是列表")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        term = re.sub(r"\s+", " ", str(item.get("term") or "")).strip()
        if not term or len(term) > 40 or term.casefold() in seen:
            continue
        raw_aliases = item.get("aliases", [])
        if not isinstance(raw_aliases, list):
            raw_aliases = []
        aliases: list[str] = []
        for value in raw_aliases:
            alias = re.sub(r"\s+", " ", str(value or "")).strip()
            if alias and len(alias) <= 40 and alias not in aliases and alias != term:
                aliases.append(alias)
        seen.add(term.casefold())
        normalized.append({"term": term, "aliases": aliases[:12]})
        if len(normalized) >= 100:
            break
    return normalized
