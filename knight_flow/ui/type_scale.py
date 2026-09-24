"""The Talk DAT! desktop type scale: seven sizes, decided once.

The desktop surfaces used to render eleven different point sizes with 85% of
every window sitting at 9-11pt, so nothing was a heading, nothing was body, and
a page of settings read as one undifferentiated block of captions. The problem
was never any single number -- it was that no two panels agreed, because each
label picked its own size at the moment it was written.

Seven steps, hand-set rather than derived from a ratio, which is what Tailwind,
Geist and Linear all settled on: a complex interface needs distinct *roles*
(page title, section heading, card title, body, note, eyebrow) and a single
ratio does not produce them.

    DISPLAY     22   the one title on a page
    TITLE       18   a large heading inside a page
    HEADING     15   section heading
    SUBHEADING  13   card title, form group label
    BODY        12   paragraphs, descriptions, help text
    SECONDARY   11   status lines and secondary notes
    CAPTION     10   eyebrows, badges, meter labels. The floor.

Which step a thing takes is decided by what it *is*, not by how it looked in
the panel it was written for. The roles that were being argued site by site:

* **What a customer types is BODY.** Their own words render at the reading
  size, in every field, on every panel. Five text inputs used to carry four
  different sizes with no reason behind any of them (X-536).
* **A code field is monospace and one step up** (SUBHEADING). That is the one
  defensible exception: a code is read back character by character and 0/O and
  1/l have to be told apart. It applies to *every* code field.
* **A field label sits one step below its field** (SECONDARY), because the
  user's words are the content and the label is chrome. Required versus
  optional is carried by weight, not by size.

Two rules travel with the numbers:

* **Nothing ships below CAPTION.** 10pt is the floor for anything a customer
  reads, and there is no eighth step waiting under it.
* **Bold is for headings.** Body copy, notes and captions are regular. Tk has
  only "normal" and "bold", so BOLD stands in for the semibold a heading wants;
  it is never applied to a paragraph.

Sizes are in points, not pixels, so Tk's own ``tk scaling`` resolves them
against the display's real DPI. Do not multiply them by ``ui_scale.px`` -- that
is for pixel-sized geometry, and doing both scales twice.

Size is only one third of a type system (X-536). Apple's own rule, from *The
Details of UI Typography*, is that **tracking and leading are size-specific and
a hierarchy is built from weight, size and leading as a set** -- so a scale that
ships seven sizes and one leading for all of them is still letting each panel
decide. ``LEADING_RATIO`` and ``TRACKING`` below close that, and
``extra_leading_px`` turns the ratio into the pixel number Tk actually wants.
"""

from __future__ import annotations

from typing import Final


DISPLAY: Final[int] = 22
TITLE: Final[int] = 18
HEADING: Final[int] = 15
SUBHEADING: Final[int] = 13
BODY: Final[int] = 12
SECONDARY: Final[int] = 11
CAPTION: Final[int] = 10

#: Every size the desktop is allowed to render, largest first.
SCALE: Final[tuple[int, ...]] = (
    DISPLAY,
    TITLE,
    HEADING,
    SUBHEADING,
    BODY,
    SECONDARY,
    CAPTION,
)

#: Nothing a customer reads is set smaller than this.
FLOOR: Final[int] = CAPTION

#: Headings carry the weight. Body, notes and captions stay regular.
BOLD: Final[str] = "bold"
REGULAR: Final[str] = "normal"


def is_on_scale(points: float) -> bool:
    """True when ``points`` is one of the seven sizes."""

    return int(points) in SCALE


def snap(points: float) -> int:
    """Return the scale step nearest to ``points``, never below the floor.

    Used where a size is computed rather than written -- a compact variant, a
    caller-supplied metric -- so an arbitrary number still lands on the scale
    instead of quietly introducing an eighth size. A tie goes to the smaller
    step, because the sizes it can fall between are one point apart and the
    denser of the two is the one that still fits whatever asked for it.
    """

    value = float(points)
    if value <= FLOOR:
        return FLOOR
    return min(SCALE, key=lambda step: (abs(step - value), step))


#: Leading (line spacing) as a multiple of the point size, per step.
#:
#: Inverse to size, which is the rule: large text is already separated by its
#: own height and reads as loose at body leading, while a caption in a dense
#: settings panel is the line most likely to be misread and needs the most air
#: relative to its size. These are targets for *rendered* leading, not the extra
#: space -- ``extra_leading_px`` does that subtraction against the real font.
LEADING_RATIO: Final[dict[int, float]] = {
    DISPLAY: 1.10,
    TITLE: 1.15,
    HEADING: 1.25,
    SUBHEADING: 1.35,
    BODY: 1.45,
    SECONDARY: 1.45,
    CAPTION: 1.50,
}

#: Tracking (letter-spacing) per step, in thousandths of an em -- the unit CSS
#: and every font tool use. Negative tightens, positive opens up. The curve is
#: the standard one: letters read too far apart as type grows, and too tight as
#: it shrinks, so display tightens, body sits at zero, and captions open up.
#:
#: **Deliberately not applied by the Tk surfaces, and that is a decision rather
#: than an omission.** Tk has no letter-spacing option on any widget, and the
#: usual workaround -- inserting thin spaces between the characters -- changes
#: the string itself, so a screen reader spells the word out one letter at a
#: time and anything copied out carries U+2009 inside it. Buying a small
#: legibility gain with an accessibility loss is not a trade this app makes.
#:
#: The table lives here because this is where the sizes live, and because the
#: renderers that CAN express it read from the same decision: the marketing
#: site's CSS, and any Canvas that places its own glyphs.
TRACKING: Final[dict[int, int]] = {
    DISPLAY: -20,
    TITLE: -15,
    HEADING: -10,
    SUBHEADING: -5,
    BODY: 0,
    SECONDARY: 5,
    CAPTION: 10,
}

#: How much looser a long-form reading surface is set than dense UI at the very
#: same point size.
#:
#: Apple's rule names both ends -- "increase it for scripts with tall ascenders
#: and descenders; tighten it for dense, information-heavy UI" -- so leading is
#: a function of the reading context as well as the size. A settings row and a
#: page the customer is writing into are not the same reading task, and setting
#: them identically gets one of them wrong.
#:
#: The scratchpad had reached almost exactly this by hand (X-536): 4px of extra
#: leading against the 5px this produces. Keeping the number here rather than in
#: the panel is the whole difference between a value that was tuned once and a
#: value the next surface will also get right.
PROSE_LEADING_BONUS: Final[float] = 0.15

#: Points to pixels at Tk's reference 72dpi-to-96dpi ratio. Callers that know
#: the real ``tk scaling`` should pass it; this is the sane default.
POINTS_TO_PIXELS: Final[float] = 96.0 / 72.0


def leading_ratio(points: float, *, prose: bool = False) -> float:
    """The target leading for ``points``, as a multiple of the point size.

    Pass ``prose=True`` for a surface the customer reads or writes at length --
    the scratchpad, a transcript, a practice page. Leave it off for the dense
    information UI that everything else is.
    """

    ratio = LEADING_RATIO[snap(points)]
    return ratio + PROSE_LEADING_BONUS if prose else ratio


def tracking(points: float) -> int:
    """The tracking for ``points``, in thousandths of an em.

    Read the ``TRACKING`` note before using this on a Tk widget: there is no
    way to apply it there without breaking the accessible name.
    """

    return TRACKING[snap(points)]


def extra_leading_px(
    points: float,
    natural_linespace_px: float,
    *,
    prose: bool = False,
    pixels_per_point: float = POINTS_TO_PIXELS,
) -> int:
    """Extra pixels to add between wrapped lines to hit the target leading.

    This is the number for a Tk ``Text`` widget's ``spacing2`` (and ``spacing1``
    between paragraphs). It is a *difference*: a font already renders each line
    at its own ``linespace``, and Tk's spacing options only ever add to that.

    Which is also why the large steps ask for so little. Segoe UI's natural
    linespace is already about 1.33x its size, so DISPLAY's 1.10 target is
    tighter than the font renders on its own and the honest answer is zero --
    Tk cannot pull lines closer together, and pretending otherwise would put a
    number here that does nothing. Never negative for that reason.
    """

    target = leading_ratio(points, prose=prose) * float(points) * float(pixels_per_point)
    return max(0, int(round(target - float(natural_linespace_px))))


__all__ = [
    "BOLD",
    "BODY",
    "CAPTION",
    "DISPLAY",
    "FLOOR",
    "HEADING",
    "LEADING_RATIO",
    "POINTS_TO_PIXELS",
    "PROSE_LEADING_BONUS",
    "REGULAR",
    "SCALE",
    "SECONDARY",
    "SUBHEADING",
    "TITLE",
    "TRACKING",
    "extra_leading_px",
    "is_on_scale",
    "leading_ratio",
    "snap",
    "tracking",
]
