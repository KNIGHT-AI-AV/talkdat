"""Unicode document layout with shaped graphemes and the exact source attached.

The fpdf2 interfaces used here are pinned and covered by document/packaging
acceptance. Its replaceable source ships separately under its own license.
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata
from pathlib import Path

import fpdf
import regex

if getattr(sys, "frozen", False):
    expected = Path(sys._MEIPASS) / "pdf_runtime" / "fpdf"
    if Path(fpdf.__file__).resolve().parent != expected.resolve():
        raise RuntimeError(
            "PDF support is incomplete. Reinstall Talk DAT, or save as Word or text."
        )

from fpdf import FPDF
from fpdf.output import OutputProducer, PDFType3Font
from fpdf.syntax import Name

GRAPHEMES = regex.compile(r"\X")
IGNORABLE = regex.compile(r"[\p{Cf}\p{Cc}\p{Variation_Selector}]")
EMOJI = regex.compile(r"\p{Emoji_Presentation}|\p{Regional_Indicator}|\u20e3")
PICTOGRAPH = regex.compile(r"\p{Extended_Pictographic}")


def font_paths() -> dict[str, Path]:
    if sys.platform == "win32":
        root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        names = {
            "sans": "arial.ttf",
            "sansb": "arialbd.ttf",
            "serif": "times.ttf",
            "serifb": "timesbd.ttf",
            "mono": "cour.ttf",
            "monob": "courbd.ttf",
            "indic": "Nirmala.ttf",
            "cjk": "msyh.ttc",
            "korean": "malgun.ttf",
            "symbols": "seguisym.ttf",
            "emoji": "seguiemj.ttf",
        }
        return {name: root / filename for name, filename in names.items()}
    if sys.platform == "darwin":
        root = Path("/System/Library/Fonts")
        names = {
            "sans": "Arial.ttf",
            "sansb": "Arial Bold.ttf",
            "serif": "Times New Roman.ttf",
            "serifb": "Times New Roman Bold.ttf",
            "mono": "Courier New.ttf",
            "monob": "Courier New Bold.ttf",
            "indic": "Devanagari Sangam MN.ttc",
            "cjk": "Arial Unicode.ttf",
        }
        result = {
            name: root / "Supplemental" / filename for name, filename in names.items()
        }
        result["emoji"] = root / "Apple Color Emoji.ttc"
        result["indic"] = root / "Kohinoor.ttc"
        return result
    root = Path("/usr/share/fonts/truetype/dejavu")
    names = {
        "sans": "DejaVuSans.ttf",
        "sansb": "DejaVuSans-Bold.ttf",
        "serif": "DejaVuSerif.ttf",
        "serifb": "DejaVuSerif-Bold.ttf",
        "mono": "DejaVuSansMono.ttf",
        "monob": "DejaVuSansMono-Bold.ttf",
    }
    result = {name: root / filename for name, filename in names.items()}
    result.update(
        {
            "cjk": Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            "emoji": Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
        }
    )
    return result


class _Output(OutputProducer):
    def _add_fonts(self, *args, **kwargs):
        fonts = super()._add_fonts(*args, **kwargs)
        # PDFKit omits emoji from copied text when a color Type3 font lacks
        # ascent/descent metrics. Supply the real font's descriptor.
        for obj in fonts.values():
            if isinstance(obj, PDFType3Font):
                descriptor = obj._font3.base_font.desc
                descriptor.font_name = Name(str(obj.name))
                self._add_pdf_obj(descriptor, "fonts")
                obj.font_descriptor = descriptor
        return fonts


class Document(FPDF):
    def __init__(self, background=None):
        super().__init__(unit="pt", format="Letter")
        self._paths = font_paths()
        self._background = background
        self._line_text = None
        self._synthetic_lrm = False
        self._font_choices = {}
        self._emoji_sets = []
        self.set_text_shaping(True)
        self.set_creator("Talk DAT!")

    def __enter__(self):
        return self

    def __exit__(self, *_error):
        for font in self.fonts.values():
            face = getattr(font, "ttfont", None)
            if face is not None:
                face.close()

    def header(self):
        if self._background:
            self.set_fill_color(*(round(x * 255) for x in self._background))
            self.rect(0, 0, self.w, self.h, style="F")

    def _load_font(self, family):
        if family in self.fonts:
            return True
        path = self._paths.get("emoji" if family.startswith("emoji") else family)
        if path is None or not path.is_file():
            return False
        self.add_font(family, fname=path)
        flags = self.fonts[family].ttfont["OS/2"].fsType
        if flags & (0x2 | 0x100 | 0x200):
            self.fonts[family].ttfont.close()
            del self.fonts[family]
            raise ValueError(
                "This system font does not allow a subset in the PDF. Save as Word or text instead."
            )
        return True

    def face(self, family, size):
        if not self._load_font(family):
            raise ValueError(
                "A required document font is unavailable. Save as Word or text instead."
            )
        self.set_font(family, size=size)

    def _choose_font(self, cluster, original):
        key = (original, cluster)
        if key in self._font_choices:
            return self._font_choices[key]
        required = {ord(c) for c in cluster if not IGNORABLE.fullmatch(c)}
        emoji = EMOJI.search(cluster) or (
            PICTOGRAPH.search(cluster) and ("\ufe0f" in cluster or "\u200d" in cluster)
        )
        candidates = (
            ["emoji", original, "indic", "cjk", "korean", "symbols"]
            if emoji
            else [original, "indic", "cjk", "korean", "symbols", "emoji"]
        )
        for family in candidates:
            if not self._load_font(family) or not required.issubset(
                self.fonts[family].cmap
            ):
                continue
            if family == "emoji":
                # Type3 fonts have an 8-bit glyph index. Bound each color
                # subset before shaping, including a document full of emoji.
                codes = {ord(c) for c in cluster}
                index = next(
                    (
                        i
                        for i, used in enumerate(self._emoji_sets)
                        if len(used | codes) <= 96
                    ),
                    None,
                )
                if index is None:
                    index = len(self._emoji_sets)
                    self._emoji_sets.append(set())
                self._emoji_sets[index].update(codes)
                family = "emoji" if index == 0 else f"emoji{index}"
                self._load_font(family)
            self._font_choices[key] = family
            return family
        raise ValueError(
            "A character has no matching system font. Save as Word or text to preserve it."
        )

    def _parse_chars(self, text, markdown):
        # Font fallback must choose a whole grapheme, so a family emoji or
        # Indic syllable cannot be split into unrelated fonts.
        original = (self.font_family, self.font_style, self.current_font)
        try:
            runs = []
            for cluster in GRAPHEMES.findall(text):
                family = self._choose_font(cluster, original[0])
                if runs and runs[-1][0] == family:
                    runs[-1][1] += cluster
                else:
                    runs.append([family, cluster])
            for family, run in runs:
                self.font_family, self.font_style, self.current_font = (
                    family,
                    "",
                    self.fonts[family],
                )
                yield from super()._parse_chars(run, False)
        finally:
            self.font_family, self.font_style, self.current_font = original

    def _render_styled_text_line(self, line, *args, **kwargs):
        previous = self._line_text
        self._line_text = "".join(
            "".join(fragment.characters) for fragment in line.fragments
        )
        if self._synthetic_lrm and self._line_text.startswith("\u200e"):
            self._line_text = self._line_text[1:]
        try:
            return super()._render_styled_text_line(line, *args, **kwargs)
        finally:
            self._line_text = previous

    def _out(self, content):
        if self._line_text is not None and re.search(r"\b(?:Tj|TJ)\b", str(content)):
            logical = ("\ufeff" + self._line_text).encode("utf-16-be").hex().upper()
            content = (
                "/Span << /ActualText <"
                + logical
                + "> >> BDC\n"
                + str(content)
                + "\nEMC"
            )
        return super()._out(content)

    def text_block(self, text, family, size, leading, color, align="L"):
        self.face(family, size)
        self.set_text_color(*(round(x * 255) for x in color))
        # Break only between complete graphemes, using shaped glyph widths.
        # FPDF's character-level fallback can split a ZWJ sequence when a
        # long unspaced run reaches the edge of a page.
        clusters = GRAPHEMES.findall(text or " ")
        available = self.epw - self.c_margin * 2 - 0.25
        offset = 0
        widths = {}
        while offset < len(clusters):
            lower, upper = 1, min(512, len(clusters) - offset)
            fit = 0
            while lower <= upper:
                count = (lower + upper) // 2
                fragment = "".join(clusters[offset : offset + count])
                width = widths.get(fragment)
                if width is None:
                    width = self.get_string_width(fragment)
                    widths[fragment] = width
                if width <= available:
                    fit, lower = count, count + 1
                else:
                    upper = count - 1
            if not fit:
                raise ValueError(
                    "A text cluster is wider than the PDF page. Save as Word or text instead."
                )
            if offset + fit < len(clusters):
                boundary = next(
                    (
                        i + 1
                        for i in range(fit - 1, -1, -1)
                        if clusters[offset + i].isspace()
                    ),
                    0,
                )
                if boundary and any(
                    not c.isspace() for c in clusters[offset : offset + boundary]
                ):
                    fit = boundary
            fragment = "".join(clusters[offset : offset + fit])
            # PDFKit otherwise inherits the direction of an earlier Arabic
            # line when copying a line containing only emoji/punctuation.
            neutral = not any(
                unicodedata.bidirectional(c) in {"L", "R", "AL"} for c in fragment
            )
            self._synthetic_lrm = neutral
            try:
                self.cell(
                    w=0,
                    h=leading,
                    text=("\u200e" if neutral else "") + fragment,
                    new_x="LMARGIN",
                    new_y="NEXT",
                    align=align,
                )
            finally:
                self._synthetic_lrm = False
            offset += fit


def _face(base_name):
    if base_name.startswith("Times"):
        return "serifb" if "Bold" in base_name else "serif"
    if base_name.startswith("Courier"):
        return "monob" if "Bold" in base_name else "mono"
    return "sansb" if "Bold" in base_name else "sans"


def render_document(text, *, title, meta, spec, report=False):
    if not isinstance(text, str) or len(text) > 1_000_000:
        raise ValueError("The document is too large for a PDF. Save as text instead.")
    if any(
        ord(c) < 32 and c not in "\n\r\t" or 0xD800 <= ord(c) <= 0xDFFF
        for c in text + title + meta
    ):
        raise ValueError(
            "The document contains an unsupported control character. Save as text instead."
        )
    margin = 64 if report else spec["margin"]
    ink = spec["body_rgb"] if report else spec["ink"]
    accent = spec["rule_rgb"] if report else spec["accent"]
    title_ink = spec["heading_rgb"] if report else ink
    with Document(None if report else spec["bg"]) as pdf:
        pdf.set_margins(margin, margin, margin)
        pdf.set_auto_page_break(True, margin + 22)
        pdf.set_title(title)
        pdf.set_subject("Dictated document")
        pdf.add_page()
        title_size = spec["subject_size"] if report else spec["title_size"]
        title_font = _face(spec["subject_font"] if report else spec["title_font"])
        alignment = "C" if not report and spec["center_title"] else "L"
        if not report and spec["caps_title"]:
            title = title.upper()
        if report and spec["accent_bar"]:
            pdf.set_fill_color(*(round(x * 255) for x in accent))
            pdf.rect(margin - 14, pdf.y, 5, title_size * 1.3, style="F")
        pdf.text_block(
            title, title_font, title_size, title_size * 1.2, title_ink, alignment
        )
        pdf.ln(10)
        pdf.text_block(meta, "sans", 8.5, 12, spec["meta_rgb"] if report else accent)
        pdf.ln(10)
        if (report and spec["rule_width"]) or (not report and spec["rule"]):
            pdf.set_draw_color(*(round(x * 255) for x in accent))
            pdf.set_line_width(spec["rule_width"] if report else 1.2)
            pdf.line(margin, pdf.y, 612 - margin, pdf.y)
        pdf.ln(16)
        body_font = _face(spec["body_font"])
        leading = spec["body_size"] * 1.55 if report else spec["leading"]
        first = True
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            face = (
                _face(spec["lede_font"])
                if report and first and line.strip()
                else body_font
            )
            pdf.text_block(line.expandtabs(4), face, spec["body_size"], leading, ink)
            if line.strip():
                first = False
        if report or spec["page_numbers"]:
            count = pdf.pages_count
            pdf.set_auto_page_break(False)
            for page in range(1, count + 1):
                pdf.page = page
                # We revisit already-written pages. Their last font can differ
                # from the global cached font left by the previous footer.
                pdf.font_family = ""
                pdf.set_xy(margin, 792 - margin / 2)
                label = f"Prepared with Talk DAT!    |    Page {page} of {count}"
                pdf.text_block(
                    label, "sans", 8, 10, spec["meta_rgb"] if report else accent, "C"
                )
            pdf.page = count
        # Complex-script selection differs across readers. Keep the exact original
        # UTF-8 text in the PDF as well as its shaped visual representation.
        pdf.embed_file(
            bytes=b"\xef\xbb\xbf" + text.encode("utf-8"),
            basename="dictated-text.txt",
            mime_type="text/plain",
            desc="Complete exported text, including its spacing",
            compress=True,
        )
        return bytes(pdf.output(output_producer_class=_Output))
