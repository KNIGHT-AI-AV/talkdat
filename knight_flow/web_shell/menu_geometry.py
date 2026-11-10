"""Pill-anchored menu geometry. Windows bounds are physical screen pixels."""

import math

#: The Pill menu's sizes in CSS pixels at 100% (2026-10-09 redesign). shell.css
#: declares the same numbers as --menu-w, --menu-pad, --menu-header, --menu-row,
#: --menu-update and --menu-sep; tests/test_the_menu_fits_its_window.py keeps the
#: two in step, so the window is exactly as tall as its content.
MENU_METRICS = {"width": 288, "max_width": 360, "pad": 4, "header": 44, "row": 32, "update": 49, "separator": 9}
#: 0.4.177 IA phase 3 (PHASE2-REVIEW-0477.md decision 1): "width" is the floor and "max_width" the cap. Between them
#: the menu is as wide as its widest row needs, which the page measures (shell.js menuViewWidth, MENU_WIDTH) as it
#: measures each view's height, and sends with it (menu_fit). shell.css declares the pair as --menu-w and --menu-w-max.
#: 0.4.177: WinUI MenuFlyout's numbers (FLUENT-MENUS-SPEC.md B1-B3): the presenter's 2 px inset, a 29 px row
#: (20 px text padded 4 and 5) inset 2 above and below, a 1 px divider between 1 px gaps. The top level has no
#: heading; the 44 px one is the in-place submenu's, the fallback where no submenu window exists.


def menu_height(rows, *, update=False, separators=1, header=False):
    """The content height of a menu view with `rows` rows, at 100%."""
    m = MENU_METRICS
    return (2 * m["pad"] + (m["header"] if header else 0) + (m["update"] if update else 0)
            + int(rows) * m["row"] + int(separators) * m["separator"])


def menu_width(width=None):
    """The menu's width in CSS px at 100%: what its widest row needs, held between the floor and the cap.

    Before the page has measured (None), the floor. A fraction rounds up, so the last pixel of a row is never cut.
    """
    low, high = MENU_METRICS["width"], MENU_METRICS["max_width"]
    if width is None:
        return low
    return max(low, min(high, int(math.ceil(float(width) - 1e-9))))


def _room(pill, work_area, scale):
    """Space for the menu above and below the Pill, after the margin and the gap."""
    left, top, right, bottom = work_area
    px, py, pw, ph = pill
    margin, gap = round(8 * scale), round(10 * scale)
    return py - top - margin - gap, bottom - (py + ph) - margin - gap


def pill_menu_side(pill, work_area, scale=1.0, *, height=None):
    """Which side of the Pill the menu opens on, chosen ONCE, at open, for Home.

    Above when Home fits there (or at least 320 px does), else the roomier side.
    Every later view keeps it (Overwatch's review B2, 2026-10-10: choosing again
    from each view's own height moved a submenu to the other side of the Pill).
    """
    scale = max(1.0, min(4.0, float(scale)))
    above, below = _room(pill, work_area, scale)
    preferred = round((height if height else 552) * scale)
    if above >= min(preferred, round(320 * scale)):
        return "above"
    return "below" if below > above else "above"


def pill_menu_bounds(pill, work_area, scale=1.0, *, height=None, side=None, width=None):
    """The menu's window on the given side of the Pill: against it, never over it.

    A view taller than the room on that side is capped there (its list scrolls). `width` is what the page measured
    its widest row needs (CSS px at 100%, held by menu_width); the window takes it at the monitor's scale, rounded
    up to the device pixel, centred on the Pill, and never wider than the screen.
    """
    left, top, right, bottom = work_area
    px, py, pw, ph = pill
    scale = max(1.0, min(4.0, float(scale)))
    margin, gap = round(8 * scale), round(10 * scale)
    width = min(math.ceil(menu_width(width) * scale - 1e-9), right-left-2*margin)
    above, below = _room(pill, work_area, scale)
    preferred = round((height if height else 552)*scale)
    if side not in ("above", "below"):
        side = pill_menu_side(pill, work_area, scale, height=height)
    if side == "above":
        height = max(1, min(preferred, above))
        y = py-gap-height
    else:
        height = max(1, min(preferred, below))
        y = py+ph+gap
    x = min(max(left+margin, round(px+pw/2-width/2)), right-margin-width)
    # A Pill stranded where an unplugged monitor used to be still gets a menu on
    # the screen Windows resolved for it (2026-10-09); on-screen Pills are unchanged.
    y = min(max(y, top+margin), bottom-margin-height)
    return [int(x), int(y), int(width), int(height)]


def submenu_bounds(row, size, work_area, scale=1.0):
    """Where a submenu opens, beside the row that opened it, as WinUI places it (the owner's order of 2026-11-05).

    CascadingMenuHelper.cpp (FLUENT-MENUS-SPEC.md B6): the left edge 4 px inside the row's right edge and the top on
    the row's top; with no room on the right, mirrored to the left with the same overlap, else right-aligned to the
    screen; with no room below, upward with its bottom on the row's bottom, else from the screen's top; never larger
    than the screen. `row` is (x, y, width, height) and `size` (width, height), physical pixels; `work_area` is the
    monitor's (left, top, right, bottom); the overlap scales with the display.
    """
    left, top, right, bottom = work_area
    x, y, row_width, row_height = row
    scale = max(1.0, min(4.0, float(scale)))
    overlap = round(4 * scale)
    width, height = min(int(size[0]), right - left), min(int(size[1]), bottom - top)
    sub_x = x + row_width - overlap
    if sub_x + width > right:
        mirrored = x - width + overlap
        sub_x = mirrored if mirrored >= left else right - width
    sub_y = y
    if sub_y + height > bottom:
        upward = y + row_height - height
        sub_y = upward if upward >= top else top
    return [int(sub_x), int(sub_y), int(width), int(height)]


def feature_bounds(base, work_area, expanded):
    x,y,width,height = base
    left,top,right,bottom = work_area
    if not expanded:
        return list(base), 'right'
    margin = 8
    extra = min(width, right-left-2*margin-width)
    if extra < 260:
        # A narrow monitor uses a second view within the same menu window.
        return list(base), 'replace'
    if x+width+extra <= right-margin:
        return [x,y,width+extra,height], 'right'
    if x-extra >= left+margin:
        return [x-extra,y,width+extra,height], 'left'
    return [left+margin,y,width+extra,height], 'right'
