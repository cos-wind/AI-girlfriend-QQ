"""Read tail of a backend service's startup log for in-app display.

Read-only helper. It never starts, stops or reconfigures any service, and it
only touches a fixed whitelist of log paths — the caller passes a service key,
never a filesystem path. Text is decoded as UTF-8 (with replacement) so CJK
logs no longer turn into mojibake, and ANSI colour escapes from third-party
tools (AstrBot/MaiBot) are stripped before display.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

_RECORD_TIME = re.compile(
    r'^\s*\[?(?:(?:(\d{4})[-/])?(\d{2})[-/](\d{2})[ T])?'
    r'(\d{2}):(\d{2})(?::(\d{2}))?(?:[.,](\d+))?'
)


def chronological(*streams: str, newest_first: bool = False) -> str:
    """Sort timestamped records, keeping continuation/traceback lines intact.

    Untimestamped preambles retain their order before dated records (after them
    with newest_first=True). Sorting reverses records, never traceback lines.
    Time-only DSH records are aligned by their last day; midnight transitions
    within each stream retain their original order. No dates are invented in
    the displayed text.
    Input is already a bounded tail; this never reads additional files.
    """
    groups = []
    dated = []
    for stream in streams:
        records = []
        lines = []
        stamp = None
        for line in ANSI_RE.sub('', stream).replace('\r\n', '\n').splitlines():
            match = _RECORD_TIME.match(line)
            if match:
                year, month, day, hour, minute, second, fraction = match.groups()
                try:
                    parsed = datetime(int(year or 2000), int(month or 1), int(day or 2),
                                      int(hour), int(minute), int(second or 0),
                                      int(((fraction or '') + '000000')[:6]))
                except ValueError:
                    lines.append(line)
                    continue
                if lines:
                    records.append((stamp, '\n'.join(lines)))
                stamp = (parsed, bool(month))
                if month:
                    dated.append(parsed.date())
                lines = []
            lines.append(line)
        if lines:
            records.append((stamp, '\n'.join(lines)))
        groups.append(records)
    records = []
    last_day = max(dated, default=date(2000, 1, 2))
    for group in groups:
        current_day, next_stamp = last_day, None
        aligned = []
        for stamp, record in reversed(group):
            value = datetime.min
            if stamp:
                parsed, has_date = stamp
                value = parsed if has_date else datetime.combine(current_day, parsed.time())
                if not has_date and next_stamp and value - next_stamp > timedelta(hours=12):
                    value -= timedelta(days=1)
                current_day, next_stamp = value.date(), value
            aligned.append((value, record))
        records.extend(reversed(aligned))
    return '\n'.join(record for _, record in sorted(records, key=lambda r: r[0], reverse=newest_first))


def _format_jsonl(text: str) -> str:
    """Render MaiBot's JSONL lines as ``timestamp level event`` for display."""
    out: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            out.append(line)
            continue
        if not isinstance(row, dict):
            out.append(line)
            continue
        stamp = str(row.get("timestamp") or "").strip()
        level = str(row.get("level") or "").strip().upper()
        event = str(row.get("event") or row.get("message") or "").strip()
        prefix = " ".join(x for x in (stamp, level) if x)
        out.append((prefix + " " + event).strip() if prefix else event)
    return "\n".join(out)

# service key -> (display name, max bytes to read from the tail)
# Byte cap keeps a multi-MB log (MaiBot) cheap to read for a quick preview.
_SERVICES: dict[str, str] = {
    "napcat": "NapCat",
    "snowluma": "SnowLuma",
    "maibot": "MaiBot",
    "astrbot": "AstrBot",
    "astrbot-trial": "AstrBot · ATRI 接入实例",
}
_MAX_BYTES = 24_000


def service_names() -> dict[str, str]:
    return dict(_SERVICES)


def _napcat_log() -> Path | None:
    """Newest *.log under the dedicated NapCat install (same rule as open_log)."""
    from .service_login import _config_path
    config = _config_path('napcat')
    root = config.parent.parent if config else None
    if not root:
        return None
    logs = [p for p in (root / "logs").glob("*.log") if p.is_file()]
    if not logs:
        return None
    return max(logs, key=lambda p: p.stat().st_mtime_ns)


def _maibot_log() -> Path | None:
    """Newest readable MaiBot log.

    MaiBot's own ``logs/startup.log`` is written corrupt (GBK bytes inside
    UTF-16) and cannot be recovered. Its ``app_*.log.jsonl`` files are clean
    UTF-8, so prefer the newest one and fall back to startup.log.
    """
    from .maibot_launcher import MaiBotLauncher

    base = MaiBotLauncher()._installation() / "logs"
    jsonl = [p for p in base.glob("app_*.log.jsonl") if p.is_file()]
    if jsonl:
        return max(jsonl, key=lambda p: p.stat().st_mtime_ns)
    startup = base / "startup.log"
    return startup if startup.is_file() else None


def _resolve(service: str) -> Path | None:
    if service == "astrbot-trial":
        from .snowluma_trial import trial_directory
        directory = trial_directory()
        log = directory / 'astrbot.log'
        if not log.is_file():
            log = directory / 'supervisor.log'
        return log if log.is_file() else None
    if service == "napcat":
        return _napcat_log()
    if service == "snowluma":
        from .snowluma_launcher import SnowLumaLauncher

        _, log = SnowLumaLauncher()._paths()
        return log if log.is_file() else None
    if service == "maibot":
        return _maibot_log()
    if service == "astrbot":
        from .astrbot_launcher import AstrBotLauncher

        log = AstrBotLauncher()._log_path()
        return log if log.is_file() else None
    return None


def _looks_utf16le(data: bytes) -> bool:
    sample = data[:600]
    if len(sample) < 8:
        return False
    pairs = sample[1::2]
    return bool(pairs) and pairs.count(0) >= max(4, len(pairs) * 0.4)


def _decode(data: bytes) -> str:
    """Decode a log slice.

    Handles BOM'd files, pure UTF-8, and mixed files where a third-party tool
    appended UTF-16LE bytes after UTF-8 content (MaiBot does this). Detection
    is local to the slice so a later UTF-16 region is decoded correctly.
    """
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig", errors="replace")
    if _looks_utf16le(data):
        return data.decode("utf-16-le", errors="replace")
    return data.decode("utf-8", errors="replace")


def _read_range(stream, start: int, end: int) -> str:
    stream.seek(start)
    return _decode(stream.read(end - start))


def _score_text(text: str) -> int:
    """Readability score: printable ASCII + CJK good, replacement/private bad."""
    good = bad = 0
    for ch in text:
        o = ord(ch)
        if ch in "\r\n\t":
            continue
        if 0x20 <= o <= 0x7E or 0x4E00 <= o <= 0x9FFF or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF:
            good += 1
        elif o == 0xFFFD or 0xE000 <= o <= 0xF8FF or o < 0x20:
            bad += 3
        else:
            bad += 1
    return good - bad


def _decode_mixed(data: bytes) -> str:
    """Decode a slice that may switch from UTF-8 to UTF-16LE mid-file.

    Candidate split points are line boundaries (a 0x0A byte and the UTF-16LE
    newline 0x0A 0x00), plus the slice ends. Every candidate is decoded both
    ways and the most readable result wins — the true encoding switch sits on a
    line boundary in practice.
    """
    total = len(data)
    candidates = {0, total}
    idx = data.find(b"\n")
    while idx != -1:
        candidates.add(idx + 1)          # right after a UTF-8 newline
        candidates.add(idx + 2)          # right after a UTF-16LE newline (0A 00)
        idx = data.find(b"\n", idx + 1)
    # Cap the work: keep boundaries nearest the first NUL (the likely switch).
    first_nul = data.find(b"\x00")
    ordered = sorted(candidates)
    if first_nul > 0 and len(ordered) > 80:
        ordered = sorted(ordered, key=lambda c: abs(c - first_nul))[:80]
    best = None
    for c in ordered:
        head = data[:c].decode("utf-8", errors="replace")
        tail = data[c:].decode("utf-16-le", errors="replace")
        text = (head + "\n" + tail) if (head and tail) else (head or tail)
        score = _score_text(text)
        if best is None or score > best[0]:
            best = (score, text)
    return best[1] if best else data.decode("utf-8", errors="replace")


def _gbk_in_utf16(data: bytes) -> str | None:
    """Recover text a broken tool wrote as GBK bytes inside UTF-16LE units.

    MaiBot's logger stores each *byte* of GBK text in one UTF-16LE unit, so the
    high byte is 0 for ASCII but a GBK lead/trail byte (often >=0x80) fills the
    whole unit for Chinese. Rebuilding the byte stream from the low bytes and
    decoding as GB18030 restores the original; returns None if it doesn't help.
    """
    if len(data) % 2 == 1:
        data = data[:-1]
    units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
    raw = bytes(u & 0xFF for u in units)
    if raw.count(0) > len(raw) * 0.05:
        return None
    # GBK text stored one byte per unit; a few bytes may not form valid GBK,
    # so decode leniently and keep it only if clearly more readable.
    recovered = raw.decode("gb18030", errors="replace")
    plain = data.decode("utf-16-le", errors="replace")
    return recovered if _score_text(recovered) > _score_text(plain) else None


def _tail_bytes(path: Path, limit: int) -> str:
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        start = max(0, size - limit)
        stream.seek(start)
        data = stream.read(limit)
        if not data:
            return ""
        nul = data.count(0)
        # Pure UTF-16LE slice (possibly GBK-in-UTF16), or a mixed UTF-8/UTF-16 slice.
        if _looks_utf16le(data) or nul > len(data) * 0.10:
            fixed = _gbk_in_utf16(data)
            if fixed is not None:
                return fixed
            return _decode(data) if _looks_utf16le(data) else _decode_mixed(data)
    return _decode(data)


def read_tail(service: str, max_bytes: int = _MAX_BYTES) -> dict[str, Any]:
    """Return current login information plus a bounded log tail.

    ``available`` means there is displayable content, including login info
    when a service has not created a log yet. No credentials are written out.
    """
    if service not in _SERVICES:
        raise ValueError("未知的服务")
    from .service_login import login_info

    name = _SERVICES[service]
    login = login_info(service)
    path = None
    size = 0
    text = ''
    limit = min(_MAX_BYTES, max(1, int(max_bytes)))
    try:
        path = _resolve(service)
        if path is not None and path.is_file():
            size = path.stat().st_size
            raw = _tail_bytes(path, limit)
            if path.suffix == ".jsonl":
                raw = _format_jsonl(raw)
            text = ANSI_RE.sub("", raw).replace("\r\n", "\n").rstrip("\n")
            if size > limit and "\n" in text:
                text = text.split("\n", 1)[1]
    except (OSError, ValueError, TypeError, AttributeError):
        text = '暂时无法读取日志，请稍后刷新。'
    text = chronological(text, newest_first=True)
    if login:
        text = f'{name} 当前登录信息\n{login}\n\n最新日志：\n' + (text or '尚无日志记录。')
    return {
        "ok": True,
        "available": bool(text) or bool(path and path.is_file()),
        "has_login_info": bool(login),
        "name": name,
        "text": text,
        "path": str(path) if path else '',
        "size": size,
    }
