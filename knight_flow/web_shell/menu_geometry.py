"""Pill-anchored menu geometry. Windows bounds are physical screen pixels."""


def pill_menu_bounds(pill, work_area, scale=1.0):
    left, top, right, bottom = work_area
    px, py, pw, ph = pill
    scale = max(1.0, min(4.0, float(scale)))
    margin, gap = round(8 * scale), round(10 * scale)
    width = min(round(304 * scale), right-left-2*margin)
    above = py-top-margin-gap
    below = bottom-(py+ph)-margin-gap
    preferred = round(552*scale)
    if above >= min(preferred, round(320*scale)):
        height = min(preferred, above)
        y = py-gap-height
    elif below > above:
        height = min(preferred, max(round(240*scale), below), bottom-top-2*margin)
        y = min(py+ph+gap, bottom-margin-height)
    else:
        height = min(preferred, bottom-top-2*margin)
        y = max(top+margin, py-gap-height)
    x = min(max(left+margin, round(px+pw/2-width/2)), right-margin-width)
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
