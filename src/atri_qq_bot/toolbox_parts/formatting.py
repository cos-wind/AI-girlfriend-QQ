from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import urlparse


def _decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return data.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")

def _extract_html_title(text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
    return _clean_html_text(match.group(1)) if match else ""

def _extract_meta_description(text: str) -> str:
    patterns = [
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return _clean_html_text(match.group(1))
    return ""

def _extract_readable_text(text: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_html_text(text)

def _clean_html_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def _extract_bvid(text: str) -> str:
    match = re.search(r"BV[0-9A-Za-z]{8,14}", text or "")
    return match.group(0) if match else ""

def _clean_bilibili_title(title: str) -> str:
    return re.sub(r"_哔哩哔哩_bilibili\s*$", "", title).strip()

def _looks_authoritative(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    return domain.endswith((".gov", ".edu", ".edu.cn", ".gov.cn")) or any(
        token in domain for token in ("who.int", "stats.gov", "pbc.gov", "mof.gov", "worldbank.org")
    )

def _shorten(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"

def _summarize_json(value: Any) -> str:
    if isinstance(value, dict):
        keys = list(value.keys())
        return f"JSON 对象：顶层字段 {len(keys)} 个，主要字段：{'、'.join(map(str, keys[:12]))}"
    if isinstance(value, list):
        sample = value[:3]
        return f"JSON 数组：共 {len(value)} 项，前几项摘要：{_shorten(json.dumps(sample, ensure_ascii=False), 600)}"
    return f"JSON 值：{_shorten(json.dumps(value, ensure_ascii=False), 600)}"

def _summarize_table_rows(rows: list[list[str]], label: str, include_samples: bool = True) -> list[str]:
    header = [str(cell).strip() for cell in (rows[0] if rows else [])]
    sample = rows[1:4]
    col_count = max((len(row) for row in rows), default=0)
    findings = [
        f"{label}：约 {max(0, len(rows) - 1)} 行数据，{col_count} 列。",
        f"{label}字段：{'、'.join(cell for cell in header[:10] if cell) or '未识别'}",
    ]
    numeric = _numeric_column_summaries(rows)
    if numeric:
        findings.append(f"{label}数值概览：" + "；".join(numeric[:5]))
    if include_samples and sample:
        findings.append(f"{label}样例：" + "；".join(" | ".join(map(str, row[:6])) for row in sample))
    return findings

def _numeric_column_summaries(rows: list[list[str]]) -> list[str]:
    if len(rows) < 2:
        return []
    header = [str(cell).strip() or f"第{index + 1}列" for index, cell in enumerate(rows[0])]
    summaries: list[str] = []
    for index, name in enumerate(header[:20]):
        values = []
        missing = 0
        for row in rows[1:]:
            raw = str(row[index]).strip() if index < len(row) else ""
            if not raw:
                missing += 1
                continue
            number = _to_float(raw)
            if number is None:
                continue
            values.append(number)
        if not values:
            continue
        avg = sum(values) / len(values)
        summaries.append(
            f"{name} count={len(values)} min={_format_number(min(values))} "
            f"max={_format_number(max(values))} avg={_format_number(avg)} missing={missing}"
        )
    return summaries

def _to_float(value: str) -> float | None:
    text = value.replace(",", "").replace("%", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None

def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}"
