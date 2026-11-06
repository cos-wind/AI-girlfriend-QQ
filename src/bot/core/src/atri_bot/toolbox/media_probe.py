from __future__ import annotations

import struct


def _image_mime_type(data: bytes) -> str:
    info = _image_info(data)
    if not info:
        return "image/png"
    kind = info[0].lower()
    if kind == "jpeg":
        return "image/jpeg"
    return f"image/{kind}"

def _image_info(data: bytes) -> tuple[str, int, int] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return ("PNG", width, height)
    if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return ("GIF", width, height)
    if data.startswith(b"\xff\xd8"):
        return _jpeg_info(data)
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return ("WEBP", 0, 0)
    return None

def _jpeg_info(data: bytes) -> tuple[str, int, int] | None:
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            break
        length = struct.unpack(">H", data[index : index + 2])[0]
        if marker in set(range(0xC0, 0xCF)) - {0xC4, 0xC8, 0xCC} and index + 7 < len(data):
            height, width = struct.unpack(">HH", data[index + 3 : index + 7])
            return ("JPEG", width, height)
        index += max(2, length)
    return None
