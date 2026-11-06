from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.parser import BytesParser


@dataclass(frozen=True)
class MultipartPart:
    name: str
    filename: str | None
    data: bytes
    charset: str = "utf-8"


MultipartForm = dict[str, list[MultipartPart]]


def parse_multipart_form(content_type: str, body: bytes) -> MultipartForm:
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("multipart/form-data is required")

    raw_message = (
        f"Content-Type: {content_type}\r\n"
        "MIME-Version: 1.0\r\n"
        "\r\n"
    ).encode("utf-8") + body
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    if not message.is_multipart():
        raise ValueError("invalid multipart body")

    form: MultipartForm = {}
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue

        data = part.get_payload(decode=True)
        if data is None:
            content = part.get_content()
            data = content.encode("utf-8") if isinstance(content, str) else bytes(content)

        field = MultipartPart(
            name=str(name),
            filename=part.get_filename(),
            data=data,
            charset=part.get_content_charset() or "utf-8",
        )
        form.setdefault(field.name, []).append(field)
    return form


def multipart_text(form: MultipartForm, name: str, default: str = "") -> str:
    part = _first_part(form, name)
    if part is None:
        return default
    return part.data.decode(part.charset, errors="replace")


def multipart_file(form: MultipartForm, name: str) -> MultipartPart | None:
    for part in form.get(name, []):
        if part.filename:
            return part
    return None


def _first_part(form: MultipartForm, name: str) -> MultipartPart | None:
    parts = form.get(name) or []
    return parts[0] if parts else None
