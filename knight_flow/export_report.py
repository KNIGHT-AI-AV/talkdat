"""X-324c: the executive-report PDF, desktop edition.

The founder's order covers every platform: "the output of the text needs
to be literally formatted onto the PDF... looks like an actual report
with a subject line and everything. Executive report styling. This is
the same for Windows PC, Mac, and iOS."

The shared Unicode renderer embeds the necessary local font subsets, shapes
complex scripts and retains the exact source as an attachment.

The structure matches iOS exactly and is DERIVED, never invented: the
subject line is the document's own first sentence (capped at a word
boundary), the first paragraph is the lede, the rest follow. No
fabricated headings.
"""

from __future__ import annotations

import time
from pathlib import Path

REPORT_DESIGNS = ("boardroom", "modern", "minimal")

_DESIGN = {
    "boardroom": {
        "subject_font": "Times-Bold", "subject_size": 22.0,
        "body_font": "Times-Roman", "body_size": 11.5, "lede_font": "Times-Bold",
        "heading_rgb": (0.12, 0.23, 0.37), "rule_rgb": (0.72, 0.57, 0.18),
        "meta_rgb": (0.42, 0.45, 0.50), "body_rgb": (0.11, 0.14, 0.19),
        "rule_width": 2.0, "accent_bar": False,
    },
    "modern": {
        "subject_font": "Helvetica-Bold", "subject_size": 23.0,
        "body_font": "Helvetica", "body_size": 11.0, "lede_font": "Helvetica-Bold",
        "heading_rgb": (0.09, 0.13, 0.17), "rule_rgb": (0.05, 0.49, 0.48),
        "meta_rgb": (0.36, 0.40, 0.44), "body_rgb": (0.09, 0.13, 0.17),
        "rule_width": 0.0, "accent_bar": True,
    },
    "minimal": {
        "subject_font": "Helvetica", "subject_size": 20.0,
        "body_font": "Helvetica", "body_size": 10.5, "lede_font": "Helvetica",
        "heading_rgb": (0.16, 0.16, 0.16), "rule_rgb": (0.89, 0.89, 0.89),
        "meta_rgb": (0.60, 0.60, 0.60), "body_rgb": (0.23, 0.23, 0.23),
        "rule_width": 1.0, "accent_bar": False,
    },
}


def derive_subject(text: str) -> str:
    """The document's own opening thought -- never an invention."""
    flat = " ".join(str(text or "").split())
    if not flat:
        return "Talk DAT! report"
    sentence = flat
    for index, ch in enumerate(flat):
        if ch in ".!?" and index >= 8:
            sentence = flat[: index]
            break
    subject = sentence.strip().rstrip(".!?")
    if len(subject) <= 80:
        return subject
    cut = subject[:80]
    space = cut.rfind(" ")
    return (cut[:space] if space > 40 else cut).rstrip() + "…"


def render_report_pdf(text: str, design: str = "boardroom", author: str = "") -> bytes:
    """Render the complete report; the caller owns publication."""
    from .pdf_documents import render_document

    spec = _DESIGN.get(design if design in _DESIGN else "boardroom", _DESIGN["boardroom"])
    meta = "  |  ".join(part for part in (time.strftime("%B %d, %Y"), str(author or "").strip()) if part)
    return render_document(text, title=derive_subject(text), meta=meta, spec=spec, report=True)


def export_report_pdf(
    text: str,
    design: str = "boardroom",
    author: str = "",
    out_dir: Path | None = None,
) -> Path:
    """Render and write; returns the file. `out_dir` exists for tests --
    production callers omit it and get the app's exports folder."""
    if out_dir is None:
        from .history import app_dir

        out_dir = app_dir() / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    from .export_files import save_new_export

    data = render_report_pdf(text, design=design, author=author)
    return save_new_export(out_dir, f"talk-dat-report-{stamp}.pdf", data)
