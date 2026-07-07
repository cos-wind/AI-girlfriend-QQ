from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree


def _docx_text_part_names(archive: zipfile.ZipFile) -> list[str]:
    names = []
    wanted_prefixes = (
        "word/document.xml",
        "word/header",
        "word/footer",
        "word/footnotes.xml",
        "word/endnotes.xml",
        "word/comments.xml",
    )
    for name in archive.namelist():
        if not name.startswith("word/") or not name.endswith(".xml"):
            continue
        if name == "word/document.xml" or any(name.startswith(prefix) for prefix in wanted_prefixes[1:]):
            names.append(name)
    return sorted(names, key=lambda item: (item != "word/document.xml", item))

def _docx_xml_to_text(data: bytes) -> str:
    root = ElementTree.fromstring(data)
    paragraphs: list[str] = []
    for paragraph in root.iter():
        if not paragraph.tag.endswith("}p"):
            continue
        pieces = [
            node.text or ""
            for node in paragraph.iter()
            if node.tag.endswith("}t") or node.tag.endswith("}instrText")
        ]
        text = "".join(pieces).strip()
        if text:
            paragraphs.append(text)
    if paragraphs:
        return "\n".join(paragraphs)
    pieces = [node.text or "" for node in root.iter() if node.tag.endswith("}t")]
    return " ".join(piece.strip() for piece in pieces if piece.strip())

def _read_xlsx_sheet_refs(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    fallback = [
        (Path(name).stem, name)
        for name in archive.namelist()
        if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
    ]
    try:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except KeyError:
        return fallback

    rel_targets: dict[str, str] = {}
    for rel in rels.iter():
        rel_id = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if not rel_id or not target:
            continue
        target = target.replace("\\", "/")
        if target.startswith("/"):
            path = target.lstrip("/")
        elif target.startswith("xl/"):
            path = target
        else:
            path = "xl/" + target.lstrip("/")
        rel_targets[rel_id] = path

    sheets: list[tuple[str, str]] = []
    for sheet in workbook.iter():
        if not sheet.tag.endswith("}sheet"):
            continue
        name = sheet.attrib.get("name") or f"sheet{len(sheets) + 1}"
        rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        path = rel_targets.get(rel_id or "")
        if path and path in archive.namelist():
            sheets.append((name, path))
    return sheets or fallback

def _read_xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    strings = []
    for item in root.iter():
        if item.tag.endswith("}si"):
            strings.append("".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")))
    return strings

def _first_xlsx_sheet_name(archive: zipfile.ZipFile) -> str:
    for name in archive.namelist():
        if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
            return name
    raise KeyError("没有找到工作表")

def _read_xlsx_sheet_rows(
    archive: zipfile.ZipFile,
    sheet_name: str,
    shared: list[str],
) -> list[list[str]]:
    root = ElementTree.fromstring(archive.read(sheet_name))
    rows: list[list[str]] = []
    for row in root.iter():
        if not row.tag.endswith("}row"):
            continue
        values: list[str] = []
        for cell in row:
            if not cell.tag.endswith("}c"):
                continue
            cell_type = cell.attrib.get("t")
            raw = ""
            for child in cell:
                if child.tag.endswith("}v") and child.text is not None:
                    raw = child.text
                    break
                if child.tag.endswith("}is"):
                    raw = "".join(node.text or "" for node in child.iter() if node.tag.endswith("}t"))
                    break
            if cell_type == "s" and raw.isdigit():
                index = int(raw)
                raw = shared[index] if index < len(shared) else raw
            values.append(raw)
        if any(value != "" for value in values):
            rows.append(values)
    return rows
