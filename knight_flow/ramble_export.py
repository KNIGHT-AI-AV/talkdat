"""X-40: an hour of talk becomes a document you can hand to someone.

Word and text use the standard library. PDF uses the shared Unicode renderer,
whose native shaping and font dependencies have explicit packaging checks.
"""

from __future__ import annotations

import datetime as _dt
import re
import zipfile
from io import BytesIO
from pathlib import Path

FORMATS = ("markdown", "word", "pdf", "text")


def ramble_folder() -> Path:
    return Path.home() / "Documents" / "Talk DAT! Rambles"


def _title_from(text: str) -> str:
    first = (text.strip().splitlines() or [""])[0]
    words: list[str] = []
    for word in first.split()[:8]:
        if len(" ".join([*words, word])) > 80:
            break
        words.append(word)
    # Retain punctuation and currency: a title must not turn 425,75 into
    # 425 75. An overlong first word gets an honest generic heading.
    return " ".join(words) or "Ramble"


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def render_markdown(text: str, when: _dt.datetime) -> bytes:
    title = _title_from(text)
    body = text
    return f"# {title}\n\n*Dictated with Talk DAT!, {when:%B %d, %Y at %H:%M}*\n\n{body}\n".encode("utf-8")


def render_text(text: str, when: _dt.datetime) -> bytes:
    return f"{_title_from(text)}\n{when:%B %d, %Y at %H:%M}, dictated with Talk DAT!\n\n{text}\n".encode("utf-8")


def render_docx(text: str, when: _dt.datetime) -> bytes:
    """A minimal, valid .docx: one document part, one style-free body."""
    if any(not (c in "\t\n\r" or '\x20' <= c <= '\ud7ff' or '\ue000' <= c <= '\ufffd' or '\U00010000' <= c <= '\U0010ffff') for c in text):
        raise ValueError("Word cannot store a control character in this text. Save as plain text instead.")
    paragraphs = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    runs = []
    title = _xml_escape(_title_from(text))
    runs.append(
        f'<w:p><w:pPr><w:jc w:val="left"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="36"/></w:rPr>'
        f"<w:t>{title}</w:t></w:r></w:p>"
    )
    stamp = _xml_escape(f"Dictated with Talk DAT!, {when:%B %d, %Y at %H:%M}")
    runs.append(f'<w:p><w:r><w:rPr><w:i/><w:color w:val="777777"/></w:rPr><w:t>{stamp}</w:t></w:r></w:p>')
    for paragraph in paragraphs:
        parts = [f'<w:t xml:space="preserve">{_xml_escape(part)}</w:t>' for part in paragraph.split("\t")]
        runs.append(f'<w:p><w:r>{"<w:tab/>".join(parts)}</w:r></w:p>')
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(runs)}</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return out.getvalue()


# Ten document looks. Font roles map to local, embeddable Unicode faces;
# no font or transcript is fetched from a network service.
PDF_TEMPLATES: dict[str, dict] = {
    "executive":  {"label": "Executive",  "title_font": "Helvetica-Bold", "body_font": "Helvetica",
                   "title_size": 22, "body_size": 11, "leading": 16, "margin": 64,
                   "bg": None, "ink": (0.12, 0.12, 0.14), "accent": (0.12, 0.12, 0.14),
                   "rule": True, "center_title": False, "caps_title": False, "page_numbers": True},
    "serif-memo": {"label": "Serif memo", "title_font": "Times-Bold", "body_font": "Times-Roman",
                   "title_size": 21, "body_size": 12, "leading": 17, "margin": 64,
                   "bg": None, "ink": (0.15, 0.13, 0.11), "accent": (0.45, 0.36, 0.26),
                   "rule": True, "center_title": False, "caps_title": False, "page_numbers": True},
    "typewriter": {"label": "Typewriter", "title_font": "Courier-Bold", "body_font": "Courier",
                   "title_size": 16, "body_size": 10, "leading": 14, "margin": 72,
                   "bg": None, "ink": (0.1, 0.1, 0.1), "accent": (0.1, 0.1, 0.1),
                   "rule": False, "center_title": False, "caps_title": False, "page_numbers": False},
    "midnight":   {"label": "Midnight",   "title_font": "Helvetica-Bold", "body_font": "Helvetica",
                   "title_size": 22, "body_size": 11, "leading": 16, "margin": 64,
                   "bg": (0.07, 0.08, 0.10), "ink": (0.88, 0.90, 0.93), "accent": (0.36, 0.72, 0.52),
                   "rule": True, "center_title": False, "caps_title": False, "page_numbers": True},
    "ivory":      {"label": "Ivory",      "title_font": "Times-Bold", "body_font": "Times-Roman",
                   "title_size": 21, "body_size": 12, "leading": 17, "margin": 68,
                   "bg": (0.97, 0.95, 0.90), "ink": (0.22, 0.17, 0.12), "accent": (0.62, 0.48, 0.30),
                   "rule": True, "center_title": False, "caps_title": False, "page_numbers": True},
    "minimal":    {"label": "Minimal",    "title_font": "Helvetica", "body_font": "Helvetica",
                   "title_size": 15, "body_size": 10, "leading": 18, "margin": 96,
                   "bg": None, "ink": (0.25, 0.25, 0.27), "accent": (0.25, 0.25, 0.27),
                   "rule": False, "center_title": False, "caps_title": True, "page_numbers": False},
    "boardroom":  {"label": "Boardroom",  "title_font": "Helvetica-Bold", "body_font": "Helvetica",
                   "title_size": 19, "body_size": 11, "leading": 16, "margin": 64,
                   "bg": None, "ink": (0.10, 0.12, 0.16), "accent": (0.10, 0.12, 0.16),
                   "rule": True, "center_title": True, "caps_title": True, "page_numbers": True},
    "manuscript": {"label": "Manuscript", "title_font": "Times-Bold", "body_font": "Times-Roman",
                   "title_size": 20, "body_size": 12, "leading": 24, "margin": 72,
                   "bg": None, "ink": (0.13, 0.12, 0.11), "accent": (0.13, 0.12, 0.11),
                   "rule": False, "center_title": True, "caps_title": False, "page_numbers": True},
    "blueprint":  {"label": "Blueprint",  "title_font": "Courier-Bold", "body_font": "Courier",
                   "title_size": 16, "body_size": 10, "leading": 14, "margin": 60,
                   "bg": (0.90, 0.94, 0.97), "ink": (0.10, 0.22, 0.38), "accent": (0.16, 0.36, 0.58),
                   "rule": True, "center_title": False, "caps_title": True, "page_numbers": True},
    "noir-gold":  {"label": "Noir gold",  "title_font": "Times-Bold", "body_font": "Times-Roman",
                   "title_size": 22, "body_size": 11, "leading": 17, "margin": 64,
                   "bg": (0.05, 0.05, 0.06), "ink": (0.92, 0.89, 0.80), "accent": (0.80, 0.64, 0.28),
                   "rule": True, "center_title": True, "caps_title": False, "page_numbers": True},
}
DEFAULT_PDF_TEMPLATE = "executive"


def render_pdf(text: str, when: _dt.datetime, template: str | None = None) -> bytes:
    """A Unicode document in one of the ten saved styles."""
    from .pdf_documents import render_document

    spec = PDF_TEMPLATES.get(str(template or "").lower(), PDF_TEMPLATES[DEFAULT_PDF_TEMPLATE])
    return render_document(text, title=_title_from(text),
        meta=f"Dictated with Talk DAT! - {when:%B %d, %Y at %H:%M}", spec=spec)


def render(text: str, fmt: str, when: _dt.datetime | None = None) -> tuple[bytes, str]:
    """Bytes + file extension for the chosen format."""
    when = when or _dt.datetime.now()
    fmt = str(fmt or "markdown").lower()
    if fmt in {"word", "docx"}:
        return render_docx(text, when), "docx"
    if fmt.startswith("pdf"):
        _, _, template = fmt.partition(":")
        return render_pdf(text, when, template or None), "pdf"
    if fmt in {"text", "plain", "txt"}:
        return render_text(text, when), "txt"
    return render_markdown(text, when), "md"


def save_ramble(text: str, fmt: str, when: _dt.datetime | None = None) -> Path:
    when = when or _dt.datetime.now()
    data, extension = render(text, fmt, when)
    folder = ramble_folder()
    folder.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", _title_from(text)).strip("-")[:40] or "ramble"
    from .export_files import save_new_export

    return save_new_export(folder, f"{when:%Y-%m-%d %H.%M} {slug}.{extension}", data)
