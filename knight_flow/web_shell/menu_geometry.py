"""Pill-anchored menu geometry. Windows bounds are physical screen pixels."""

#: The Pill menu's sizes in CSS pixels at 100% (2026-10-09 redesign). shell.css
#: declares the same numbers as --menu-w, --menu-pad, --menu-header, --menu-row,
#: --menu-update and --menu-sep; tests/test_the_menu_fits_its_window.py keeps the
#: two in step, so the window is exactly as tall as its content.
MENU_METRICS = {"width": 288, "pad": 6, "header": 44, "row": 40, "update": 64, "separator": 9}


def menu_height(rows, *, update=False, separators=1):
    """The content height of a menu view with `rows` rows, at 100%."""
    m = MENU_METRICS
    return (2 * m["pad"] + m["header"] + (m["update"] if update else 0)
            + int(rows) * m["row"] + int(separators) * m["separator"])


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


def pill_menu_bounds(pill, work_area, scale=1.0, *, height=None, side=None):
    """The menu's window on the given side of the Pill: against it, never over it.

    A view taller than the room on that side is capped there (its list scrolls).
    """
    left, top, right, bottom = work_area
    px, py, pw, ph = pill
    scale = max(1.0, min(4.0, float(scale)))
    margin, gap = round(8 * scale), round(10 * scale)
    width = min(round(MENU_METRICS["width"] * scale), right-left-2*margin)
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
