"""Turn GitHub release Markdown into something readable in a Tk text box.

The update dialog showed the release body raw, so headings arrived as `##` and
emphasis as `**`, and the fallback when notes were empty was "See the full
release notes on GitHub" -- which asks someone deciding whether to install to go
somewhere else to find out what they are installing.

This keeps the structure that matters (headings, bullets, warnings) and drops
the syntax that does not survive a plain text widget.

2026-09-23 (owner's audit): notes were read a LINE at a time, and CHANGELOG.md
is hard-wrapped at about 78 characters. Home turned every wrapped line into its
own bullet ("... Apache 2.0 licence. The" / "name and logo stay ours; ..."), and
the What's New window read the wrapped "  7) and never your audio" as a
numbered item "7.". release_note_blocks parses blocks the way a Markdown
renderer does, and every reader of the notes goes through it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A dialog is not a web page. Past this, reading stops and scrolling starts.
MAX_CHARACTERS = 5200
MORE_NOTICE = "\n\n… trimmed. Choose View release for the full release notes."

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_RULE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_ASTERISK = re.compile(r"(\*{1,3})(.+?)\1")
# Underscores only count as emphasis at a word boundary. Treating them like
# asterisks turned STRIPE_LIVE_MODE into STRIPELIVEMODE -- every identifier,
# env var and file name in the notes would be quietly mangled, which is worse
# than leaving a stray underscore visible.
_UNDERSCORE = re.compile(r"(?<![A-Za-z0-9_])(_{1,3})(\S.*?\S|\S)\1(?![A-Za-z0-9_])")
_CODE = re.compile(r"`([^`]*)`")


def _inline(text: str) -> str:
    text = _IMAGE.sub("", text)
    text = _LINK.sub(r"\1", text)          # keep the words, drop the URL
    text = _CODE.sub(r"\1", text)
    text = _ASTERISK.sub(r"\2", text)
    text = _UNDERSCORE.sub(r"\2", text)
    return text.strip()


@dataclass(frozen=True)
class NoteBlock:
    """One block of release notes, its hard-wrapped lines joined back together.

    ``kind`` is "heading", "paragraph", "bullet", "numbered", "quote" or
    "rule". ``level`` is the list nesting depth (0 at the margin).
    """

    kind: str
    text: str = ""
    number: int | None = None
    level: int = 0


LIST_KINDS = frozenset({"bullet", "numbered"})


def _indent(line: str) -> int:
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


def release_note_blocks(notes: str | None) -> list[NoteBlock]:
    """Parse release Markdown into blocks, as a CommonMark renderer would.

    * A line that continues a paragraph or a list item is joined to it, so a
      hard-wrapped sentence stays one sentence.
    * Only "- ", "* " and "+ " start bullets.
    * A numbered line starts an item only where a list may begin: at the start
      of a block, as the next item of a numbered list, or as "1." / "1)",
      which may interrupt a paragraph. A wrapped "7) and never your audio" in
      the middle of a sentence is prose, not item seven.
    """
    blocks: list[NoteBlock] = []
    current: dict | None = None
    # Content columns of the list items that are still open, outermost first.
    open_items: list[int] = []

    def flush() -> None:
        nonlocal current
        if current is not None:
            text = _inline(" ".join(part.strip() for part in current["parts"] if part.strip()))
            if text:
                blocks.append(NoteBlock(current["kind"], text, current.get("number"), current.get("level", 0)))
        current = None

    def nest(indent: int) -> int:
        """Close the open items this line is not inside; its depth is what is left."""
        while open_items and indent < open_items[-1]:
            open_items.pop()
        return min(len(open_items), 3)

    source = (notes or "").replace("\r\n", "\n").replace("\r", "\n")
    for raw in source.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        if _RULE.match(line):
            flush()
            open_items.clear()
            blocks.append(NoteBlock("rule"))
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            open_items.clear()
            title = _inline(heading.group(1))
            if title:
                blocks.append(NoteBlock("heading", title))
            continue
        quote = _QUOTE.match(line)
        if quote:
            if current is not None and current["kind"] == "quote":
                current["parts"].append(quote.group(1))
                continue
            flush()
            current = {"kind": "quote", "parts": [quote.group(1)]}
            continue
        indent = _indent(line)
        bullet = _BULLET.match(line)
        if bullet:
            flush()
            level = nest(indent)
            current = {"kind": "bullet", "parts": [bullet.group(2)], "level": level}
            open_items.append(len(line[: bullet.start(2)].expandtabs(4)))
            continue
        numbered = _NUMBERED.match(line)
        if numbered:
            number = int(numbered.group(2))
            inside_item = bool(
                current is not None and current["kind"] in LIST_KINDS and open_items and indent >= open_items[-1]
            )
            sibling = bool(
                current is not None and current["kind"] == "numbered" and open_items and indent < open_items[-1]
            )
            may_begin = current is None or sibling or number == 1
            if may_begin and not (inside_item and number != 1):
                flush()
                level = nest(indent)
                current = {"kind": "numbered", "parts": [numbered.group(3)], "number": number, "level": level}
                open_items.append(len(line[: numbered.start(3)].expandtabs(4)))
                continue
        if current is None:
            # A new paragraph: inside an open item when indented to its
            # content, otherwise back at the margin.
            level = nest(indent)
            current = {"kind": "paragraph", "parts": [line], "level": level}
        else:
            current["parts"].append(line)
    flush()
    return blocks


def readable_release_notes(notes: str | None) -> str:
    """Flatten release Markdown into readable plain text.

    One line per block: a Text widget with wrap="word" wraps each paragraph
    and item at the window's own width, instead of at the 78 columns the
    Markdown happened to be written at.
    """
    raw = (notes or "").strip()
    if not raw:
        return "This update has no published notes yet."

    lines: list[str] = []
    previous = ""
    for block in release_note_blocks(raw):
        if block.kind == "rule":
            # A rule is a visual divider that reads as three dashes in plain
            # text. A blank line does the same job without the noise.
            if lines and lines[-1] != "":
                lines.append("")
            previous = "rule"
            continue
        # Items of one list stay together; every other block gets air.
        if lines and lines[-1] != "" and not (block.kind in LIST_KINDS and previous in LIST_KINDS):
            lines.append("")
        indent = "    " * block.level
        if block.kind == "heading":
            lines.append(block.text.upper())
        elif block.kind == "bullet":
            lines.append(f"{indent}  \u2022 {block.text}")
        elif block.kind == "numbered":
            lines.append(f"{indent}  {block.number}. {block.text}")
        elif block.kind == "quote":
            # Blockquotes carry the warnings, so keep them and mark them.
            lines.append(f"  ! {block.text}")
        else:
            lines.append(f"{indent}{block.text}")
        previous = block.kind

    # Newlines only: the two spaces before a first "•" are part of its shape.
    text = "\n".join(line.rstrip() for line in lines).strip("\n")
    if len(text) > MAX_CHARACTERS:
        cut = text.rfind("\n", 0, MAX_CHARACTERS)
        text = text[: cut if cut > 0 else MAX_CHARACTERS].rstrip() + MORE_NOTICE
    return text


def changelog_digest(section: str | None, *, limit: int = 5) -> dict:
    """What Home shows of a CHANGELOG section: its opening paragraphs, then its
    first items, each one whole. ``more`` counts the items left out."""
    blocks = release_note_blocks(section)
    keep = max(0, int(limit))
    summary = [block.text for block in blocks if block.kind == "paragraph" and block.level == 0][:2]
    items = [block.text for block in blocks if block.kind in LIST_KINDS and block.level == 0]
    return {"summary": summary, "notes": items[:keep], "more": max(0, len(items) - keep)}
