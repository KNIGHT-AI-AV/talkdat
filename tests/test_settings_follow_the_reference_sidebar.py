"""The owner, 2026-11-05, with a screenshot of a dark finance dashboard: "RESEARCH and Revamp our entire menu system
to be like this".

The shot's anatomy is shadcn/ui's sidebar system (MIT; ui/sidebar.tsx and the sidebar-07, sidebar-08 and dashboard-01
blocks). The lane's REFERENCE-SIDEBAR-SPEC.md holds every number with its source line or image pixel, and
SIDEBAR-REDESIGN-DECISIONS.md the choices (D1-D12). The shot decides what it shows, shadcn's source what a still image
cannot: a 256 px sidebar on the theme's own background with the main area 1.6% lighter; 32 px rows 4 px apart with
8 px padding, a 16 px icon, an 8 px gap, 8 px corners (the app's scale step; shadcn's rounded-md) and 14/20 text, dimmed until current (the theme's muted ink,
moved toward the text where it would not read at 4.5:1 on these surfaces); the current row a 3.8%
fill with a 6% edge and full-strength 500 text; pages nested under their group on a curved tree line; a brand row with
a collapse button, an account card under a full-width separator; a 52 px top bar with a breadcrumb, a search field
with its Ctrl K hint and a ghost Quick help; the group's pages as pill tabs; an 18/28 title over a 13/20 subtitle.
Colours are the theme's (D1). Below 768 px the sidebar is an icon rail with 44 px targets (D5).
"""
from __future__ import annotations

import unittest

from tests import shell_cascade
from tests.shell_cascade import Element, Environment, button, resolve

HTML = Element("html")
SHELL = Element("div", id="shell", parent=HTML)
COLLAPSED = Element("div", id="shell", attrs={"data-sidebar": "collapsed"}, parent=HTML)
NARROW = Environment(width=600)


def rail(shell=SHELL):
    return Element("aside", ("rail",), parent=shell)


def navigation(shell=SHELL):
    return Element("nav", id="navigation", parent=rail(shell))


def group(shell=SHELL, open_=True):
    return Element("div", ("nav-group",), attrs={"data-open": "true" if open_ else "false"}, parent=navigation(shell))


def row(*states, current="false", shell=SHELL):
    return button("nav-row", states=states, attrs={"aria-current": current}, parent=group(shell))


def child(*states, current="false", last=False, shell=SHELL):
    sub = Element("div", ("nav-sub",), parent=group(shell))
    return button("nav-row", "nav-child", states=set(states) | ({"last-child"} if last else set()),
                  attrs={"aria-current": current}, parent=sub)


def toolbar(shell=SHELL):
    return Element("header", ("toolbar",), parent=Element("div", ("workspace",), parent=shell))


def tab(*states, current="false"):
    return button(states=states, attrs={"aria-current": current},
                  parent=Element("nav", id="sections", parent=Element("div", ("workspace",), parent=SHELL)))


def root_tokens(mode=""):
    found = {}
    for _sheet, stack, selector, body in shell_cascade.shell_css.all_rules():
        if stack or selector != (":root[data-mode=light]" if mode == "light" else ":root"):
            continue
        for name, value in shell_cascade.shell_css.declarations(body):
            if name.startswith("--"):
                found[name] = " ".join(value.replace(", ", ",").split())
    return found


def compact(value):
    return " ".join((value or "").replace(", ", ",").split())


class TheColoursAreTheThemesInTheShotsProportions(unittest.TestCase):
    def test_the_surfaces_hairlines_and_fills(self):
        dark = root_tokens()
        self.assertEqual(dark["--sidebar"], "var(--bg)")
        self.assertEqual(dark["--surface-main"], "color-mix(in srgb,var(--bg),#fff 1.6%)", "lighter than the sidebar in light themes too, as shadcn's are")
        self.assertEqual(dark["--hairline"], "color-mix(in srgb,var(--text) 6%,transparent)")
        self.assertEqual(dark["--row-fill"], "color-mix(in srgb,var(--text) 3.8%,transparent)")
        self.assertEqual(dark["--row-press"], "color-mix(in srgb,var(--text) 7%,transparent)")
        self.assertEqual(dark["--tab-fill"], "color-mix(in srgb,var(--text) 4.7%,transparent)")
        self.assertEqual(dark["--field-fill"], "color-mix(in srgb,var(--text) 2.1%,transparent)")
        self.assertEqual(dark["--kbd-fill"], "color-mix(in srgb,var(--text) 6.5%,transparent)")
        self.assertEqual(dark["--card-edge"], "color-mix(in srgb,var(--text) 8%,transparent)")
        self.assertEqual(dark["--tree"], "color-mix(in srgb,var(--text) 16%,var(--sidebar))",
                         "opaque, so a branch crosses the spine without a darker joint; the shot's 10.4% is a 1 px line "
                         "blurred by its downscale, and 10% drew too faint in a real render (screens/sidebar-jade-garden-dark.png)")
        self.assertEqual(dark["--chrome-ink"], "var(--muted)", "shell.js moves it toward the text where muted would not read")
        self.assertEqual(dark["--sidebar-width"], "256px")
        self.assertEqual(dark["--sidebar-width-icon"], "48px")
        self.assertEqual(dark["--t-sidebar"], "200ms")
        self.assertEqual(dark["--t-quick"], "150ms")
        self.assertEqual(dark["--ease-ui"], "cubic-bezier(.4,0,.2,1)")
        self.assertEqual(dark["--ease-pop"], "ease", "the tooltip and the menus use tw-animate's default")

    def test_light_themes_get_shadcns_firmer_hairline(self):
        light = root_tokens("light")
        self.assertEqual(light["--hairline"], "color-mix(in srgb,var(--text) 10%,transparent)")
        self.assertEqual(light["--card-edge"], "color-mix(in srgb,var(--text) 12%,transparent)")

    def test_the_sidebar_is_darker_than_the_page(self):
        self.assertEqual(resolve(rail(), "background"), "var(--sidebar)")
        self.assertEqual(resolve(rail(), "border-right"), "1px solid var(--hairline)")
        self.assertEqual(resolve(Element("div", ("workspace",), parent=SHELL), "background"), "var(--surface-main)")
        self.assertEqual(resolve(SHELL, "padding"), "0")
        self.assertEqual(resolve(SHELL, "gap"), "0")


class ThePaneOpensAndFolds(unittest.TestCase):
    def test_it_is_256_px_and_folds_to_48_in_200_ms_linear(self):
        self.assertEqual(compact(resolve(SHELL, "grid-template-columns")), "auto minmax(0,1fr)")
        self.assertEqual(resolve(rail(), "width"), "var(--sidebar-width)")
        self.assertEqual(resolve(rail(COLLAPSED), "width"), "var(--sidebar-width-icon)")
        self.assertEqual(resolve(rail(), "transition"), "width var(--t-sidebar) linear")
        self.assertEqual(resolve(rail(), "overflow"), "hidden")

    def test_folded_it_keeps_the_icons_and_hides_the_rest(self):
        self.assertEqual(resolve(row(shell=COLLAPSED), "width"), "32px")
        self.assertEqual(resolve(row(shell=COLLAPSED), "padding"), "8px")
        for name, element in {"label": Element("span", ("nav-label",), parent=row(shell=COLLAPSED)),
                              "children": Element("div", ("nav-sub",), parent=group(COLLAPSED)),
                              "chevron": button("nav-toggle", parent=group(COLLAPSED)),
                              "wordmark": Element("div", ("wordmark",), parent=Element("div", ("rail-brand",), parent=rail(COLLAPSED)))}.items():
            with self.subTest(name):
                self.assertEqual(resolve(element, "display"), "none")

    def test_folded_the_group_you_are_in_keeps_the_current_fill(self):
        # Folded, a page's own row is hidden, so its group's icon carries the mark (shadcn: the active item's fill).
        for shell, env in ((COLLAPSED, None), (SHELL, NARROW)):
            with self.subTest(narrow=env is not None):
                self.assertEqual(resolve(row(current="true", shell=shell), "background", env), "var(--row-fill)")
                self.assertEqual(resolve(row(current="true", shell=shell), "box-shadow", env), "inset 0 0 0 1px var(--hairline)")
        self.assertEqual(resolve(row(current="true"), "background"), "transparent", "open, the page's own row carries it")

    def test_the_tooltip_is_shadcns(self):
        tip = Element("div", ("rail-tip",), parent=Element("body", parent=HTML))
        self.assertEqual(resolve(tip, "position"), "fixed")
        self.assertEqual(resolve(tip, "padding"), "6px 12px")
        self.assertEqual(resolve(tip, "border-radius"), "var(--r-sm)")
        self.assertEqual(resolve(tip, "font-size"), "12px")
        self.assertEqual(resolve(tip, "line-height"), "16px")
        self.assertEqual(resolve(tip, "background"), "var(--text)")
        self.assertEqual(resolve(tip, "color"), "var(--bg)")
        self.assertEqual(resolve(tip, "pointer-events"), "none")


class TheRowsAreTheShots(unittest.TestCase):
    def test_a_row_is_32_px_with_8_px_padding_and_6_px_corners(self):
        self.assertEqual(resolve(row(), "height"), "32px")
        self.assertEqual(resolve(row(), "padding"), "0 8px")
        self.assertEqual(resolve(row(), "gap"), "8px")
        self.assertEqual(resolve(row(), "border-radius"), "var(--r-sm)")
        self.assertEqual(resolve(row(), "margin"), "0")
        self.assertEqual(resolve(navigation(), "gap"), "4px")
        self.assertEqual(resolve(navigation(), "padding"), "0 16px")
        icon = Element("span", ("nav-icon",), parent=row())
        self.assertEqual(resolve(icon, "width"), "16px")
        self.assertEqual(resolve(icon, "height"), "16px")

    def test_the_label_is_14_on_20_dimmed_until_current(self):
        self.assertEqual(resolve(row(), "font-size"), "14px")
        self.assertEqual(resolve(row(), "line-height"), "20px")
        self.assertEqual(resolve(row(), "font-weight"), "400")
        self.assertEqual(resolve(row(), "color"), "var(--chrome-ink)")
        self.assertEqual(resolve(Element("span", ("nav-icon",), parent=row()), "color"), "var(--chrome-ink)")
        self.assertEqual(resolve(row(current="page"), "color"), "var(--text)")
        self.assertEqual(resolve(row(current="page"), "font-weight"), "500")
        self.assertEqual(resolve(Element("span", ("nav-icon",), parent=row(current="page")), "color"), "var(--text)")
        self.assertEqual(resolve(row(current="true"), "color"), "var(--text)", "the group holding the page reads at full strength")

    def test_states_are_the_shots_fills_and_change_at_once(self):
        self.assertEqual(resolve(row(), "background"), "transparent")
        self.assertEqual(resolve(row(), "box-shadow"), "none")
        self.assertEqual(resolve(row("hover"), "background"), "var(--row-fill)")
        # shadcn presses with the hover fill; Talk DAT!'s rule is that a press always shows, so it goes one step deeper.
        self.assertEqual(resolve(row("hover", "active"), "background"), "var(--row-press)")
        self.assertEqual(resolve(row(current="page"), "background"), "var(--row-fill)")
        self.assertEqual(resolve(row(current="page"), "box-shadow"), "inset 0 0 0 1px var(--hairline)")
        self.assertEqual(resolve(row(), "transition"), "none")
        self.assertEqual(resolve(row("hover", "active"), "transform"), "none")

    def test_keyboard_focus_is_a_2_px_ring_inside_the_row(self):
        # shadcn's ring-2 in the theme's ring colour, drawn inside (the menu rows' own inset) so the nav's edge never clips it.
        self.assertEqual(resolve(row("focus-visible"), "outline"), "var(--focus-width) solid var(--ring)")
        self.assertEqual(resolve(row("focus-visible"), "outline-offset"), "var(--focus-inset)")


class ThePagesHangOnTheShotsTree(unittest.TestCase):
    def test_children_line_up_with_the_parents_label(self):
        self.assertEqual(resolve(child(), "margin-left"), "24px")
        self.assertEqual(resolve(child(), "height"), "32px")
        self.assertEqual(resolve(Element("div", ("nav-sub",), parent=group()), "gap"), "4px")
        self.assertEqual(resolve(Element("div", ("nav-sub",), parent=group()), "margin-top"), "4px")

    def test_each_child_branches_off_the_spine_on_a_6_px_curve(self):
        for prop, value in {"content": '""', "position": "absolute", "left": "-9px", "top": "-4px",
                            "height": "calc(50% + 4px)", "width": "7px", "border-left": "1px solid var(--tree)",
                            "border-bottom": "1px solid var(--tree)", "border-bottom-left-radius": "6px",
                            "pointer-events": "none"}.items():
            with self.subTest(prop):
                self.assertEqual(resolve(child(), prop, pseudo="before"), value)

    def test_the_spine_runs_on_past_every_child_but_the_last(self):
        self.assertEqual(resolve(child(), "border-left", pseudo="after"), "1px solid var(--tree)")
        self.assertEqual(resolve(child(), "top", pseudo="after"), "0")
        self.assertEqual(resolve(child(), "bottom", pseudo="after"), "-4px")
        self.assertIn(resolve(child(last=True), "content", pseudo="after"), (None, "none"))

    def test_the_chevron_turns_90_degrees_in_150_ms(self):
        toggle = button("nav-toggle", attrs={"aria-expanded": "false"}, parent=group())
        opened = button("nav-toggle", attrs={"aria-expanded": "true"}, parent=group())
        self.assertEqual(resolve(toggle, "width"), "20px")
        self.assertEqual(resolve(toggle, "height"), "20px")
        self.assertEqual(resolve(toggle, "right"), "6px")
        self.assertEqual(resolve(toggle, "top"), "6px")
        self.assertEqual(resolve(toggle, "border-radius"), "var(--r-xs)")
        self.assertEqual(resolve(toggle, "transform"), "none")
        self.assertEqual(resolve(opened, "transform"), "rotate(90deg)")
        self.assertEqual(compact(resolve(toggle, "transition")), "transform var(--t-quick) var(--ease-ui)")


class TheBrandAndTheAccountCard(unittest.TestCase):
    def test_the_brand_row_is_48_px_with_a_filled_collapse_button(self):
        brand = Element("div", ("rail-brand",), parent=rail())
        self.assertEqual(resolve(brand, "height"), "48px")
        self.assertEqual(resolve(brand, "padding"), "0 16px 0 24px")
        mark = Element("span", ("brand-mark",), parent=brand)
        self.assertEqual(resolve(mark, "width"), "20px")
        self.assertEqual(resolve(mark, "border-radius"), "var(--r-xs)")
        self.assertEqual(resolve(mark, "background"), "var(--accent)")
        wordmark = Element("div", ("wordmark",), parent=brand)
        self.assertEqual(resolve(wordmark, "font-size"), "15px")
        self.assertEqual(resolve(wordmark, "font-weight"), "600")
        self.assertEqual(resolve(wordmark, "padding"), "0")
        toggle = button(attrs={}, parent=brand)
        toggle.id = "rail-toggle"
        self.assertEqual(resolve(toggle, "width"), "26px")
        self.assertEqual(resolve(toggle, "height"), "26px")
        self.assertEqual(resolve(toggle, "border-radius"), "var(--r-xs)")
        self.assertEqual(resolve(toggle, "background"), "var(--row-fill)")
        self.assertEqual(resolve(toggle, "box-shadow"), "inset 0 0 0 1px var(--hairline)")

    def test_the_account_card_sits_under_a_full_width_separator(self):
        footer = Element("div", ("rail-footer",), parent=rail())
        self.assertEqual(resolve(footer, "border-top"), "1px solid var(--hairline)")
        self.assertEqual(resolve(footer, "padding"), "16px")
        card = button(parent=footer)
        card.id = "account-card"
        self.assertEqual(resolve(card, "height"), "48px")
        self.assertEqual(resolve(card, "padding"), "0 8px")
        self.assertEqual(resolve(card, "border-radius"), "var(--r-sm)")
        self.assertEqual(resolve(card, "background"), "var(--row-fill)")
        self.assertEqual(resolve(card, "box-shadow"), "inset 0 0 0 1px var(--card-edge)")
        avatar = Element("span", ("account-avatar",), parent=card)
        self.assertEqual(resolve(avatar, "width"), "32px")
        self.assertEqual(resolve(avatar, "border-radius"), "var(--r-xs)")
        self.assertEqual(resolve(Element("span", ("account-name",), parent=card), "font-size"), "14px")
        self.assertEqual(resolve(Element("span", ("account-line",), parent=card), "font-size"), "12px")
        self.assertEqual(resolve(Element("span", ("account-line",), parent=card), "color"), "var(--chrome-ink)")


class TheTopBarIsTheShots(unittest.TestCase):
    def test_the_bar_is_52_px_over_a_hairline(self):
        self.assertEqual(resolve(toolbar(), "min-height"), "52px")
        self.assertEqual(resolve(toolbar(), "padding"), "0 24px")
        self.assertEqual(resolve(toolbar(), "border-bottom"), "1px solid var(--hairline)")

    def test_the_breadcrumb_is_muted_up_to_the_page(self):
        crumbs = Element("nav", ("breadcrumb",), parent=toolbar())
        self.assertEqual(resolve(crumbs, "gap"), "10px")
        self.assertEqual(resolve(crumbs, "font-size"), "14px")
        self.assertEqual(resolve(crumbs, "color"), "var(--chrome-ink)")
        here = Element("span", ("crumb-page",), parent=crumbs)
        self.assertEqual(resolve(here, "color"), "var(--text)")

    def test_search_is_a_30_px_field_with_its_shortcut_inside(self):
        search = Element("label", ("search",), parent=toolbar())
        self.assertEqual(resolve(search, "height"), "30px")
        self.assertEqual(resolve(search, "width"), "280px", "the shot's 263 px, widened to fit 'Search settings and tools'")
        self.assertEqual(resolve(search, "padding"), "0 5px 0 10px")
        self.assertEqual(resolve(search, "border-radius"), "var(--r-sm)")
        self.assertEqual(resolve(search, "background"), "var(--field-fill)")
        self.assertEqual(resolve(search, "box-shadow"), "inset 0 0 0 1px var(--hairline)")
        kbd = Element("kbd", ("kbd",), parent=search)
        self.assertEqual(resolve(kbd, "height"), "20px")
        self.assertEqual(resolve(kbd, "padding"), "0 6px")
        self.assertEqual(resolve(kbd, "border-radius"), "var(--r-xs)")
        self.assertEqual(resolve(kbd, "background"), "var(--kbd-fill)")
        self.assertEqual(resolve(kbd, "font-size"), "12px")
        self.assertEqual(resolve(kbd, "color"), "var(--chrome-ink)")

    def test_quick_help_is_a_ghost_button(self):
        help_ = button("quiet", parent=toolbar())
        help_.id = "help-button"
        self.assertEqual(resolve(help_, "height"), "32px")
        self.assertEqual(resolve(help_, "padding"), "0 10px")
        self.assertEqual(resolve(help_, "border-radius"), "var(--r-sm)")
        self.assertEqual(resolve(help_, "background"), "transparent")
        self.assertEqual(resolve(help_, "box-shadow"), "none")
        hovered = button("quiet", states={"hover"}, parent=toolbar())
        hovered.id = "help-button"
        self.assertEqual(resolve(hovered, "background"), "var(--row-fill)")
        self.assertEqual(resolve(Element("span", ("nav-icon",), parent=help_), "width"), "16px")
        divider = Element("span", ("toolbar-divider",), parent=toolbar())
        self.assertEqual(resolve(divider, "width"), "1px")
        self.assertEqual(resolve(divider, "height"), "16px")


class TheTabsAndTheTitle(unittest.TestCase):
    def test_the_tab_row_is_transparent_with_a_hairline_under_it(self):
        row_ = Element("nav", id="sections", parent=Element("div", ("workspace",), parent=SHELL))
        self.assertEqual(resolve(row_, "padding"), "12px 24px")
        self.assertEqual(resolve(row_, "gap"), "4px")
        self.assertEqual(resolve(row_, "border-bottom"), "1px solid var(--hairline)")

    def test_a_tab_is_a_36_px_pill_that_fills_when_current(self):
        self.assertEqual(resolve(tab(), "height"), "36px")
        self.assertEqual(resolve(tab(), "padding"), "0 12px")
        self.assertEqual(resolve(tab(), "border-radius"), "var(--r-sm)")
        self.assertEqual(resolve(tab(), "font-size"), "14px")
        self.assertEqual(resolve(tab(), "font-weight"), "500")
        self.assertEqual(resolve(tab(), "color"), "var(--chrome-ink)")
        self.assertEqual(resolve(tab(), "background"), "transparent")
        self.assertEqual(resolve(tab("hover"), "color"), "var(--text)")
        self.assertEqual(resolve(tab(current="page"), "background"), "var(--tab-fill)")
        self.assertEqual(resolve(tab(current="page"), "color"), "var(--text)")
        self.assertEqual(resolve(tab(current="page"), "box-shadow"), "none")

    def test_the_title_is_18_on_28_over_a_13_on_20_subtitle(self):
        intro = Element("div", ("intro",))
        title, subtitle = Element("h1", parent=intro), Element("p", parent=intro)
        self.assertEqual(resolve(title, "font-size"), "18px")
        self.assertEqual(resolve(title, "line-height"), "28px")
        self.assertEqual(resolve(title, "font-weight"), "600")
        self.assertEqual(resolve(subtitle, "font-size"), "13px")
        self.assertEqual(resolve(subtitle, "line-height"), "20px")
        self.assertEqual(resolve(subtitle, "color"), "var(--chrome-ink)")


class NarrowIsAnIconRailWithFortyFourPixelTargets(unittest.TestCase):
    def test_below_768_px_the_rail_shows_icons_at_44_px(self):
        self.assertEqual(resolve(rail(), "width", NARROW), "60px")
        self.assertEqual(resolve(row(), "height", NARROW), "44px")
        self.assertEqual(resolve(row(), "width", NARROW), "44px")
        self.assertEqual(resolve(navigation(), "padding", NARROW), "0 8px")
        for name, element in {"label": Element("span", ("nav-label",), parent=row()),
                              "children": Element("div", ("nav-sub",), parent=group()),
                              "chevron": button("nav-toggle", parent=group()),
                              "breadcrumb": Element("nav", ("breadcrumb",), parent=toolbar()),
                              "account words": Element("span", ("account-copy",), parent=Element("button", id="account-card")),
                              "shortcut hint": Element("kbd", ("kbd",), parent=Element("label", ("search",), parent=toolbar()))}.items():
            with self.subTest(name):
                self.assertEqual(resolve(element, "display", NARROW), "none")

    def test_every_control_in_the_chrome_is_44_px_there(self):
        search = Element("label", ("search",), parent=toolbar())
        help_ = button("quiet", parent=toolbar())
        help_.id = "help-button"
        card = Element("button", id="account-card", parent=Element("div", ("rail-footer",), parent=rail()))
        for name, element, prop in (("search", search, "height"), ("help", help_, "height"), ("tab", tab(), "height"),
                                    ("account", card, "height"), ("account", card, "width")):
            with self.subTest(name=name, prop=prop):
                self.assertEqual(resolve(element, prop, NARROW), "44px")
        toggle = Element("button", id="rail-toggle", parent=Element("div", ("rail-brand",), parent=rail()))
        self.assertEqual(resolve(toggle, "display", NARROW), "none", "the rail cannot open wider than the window allows")


if __name__ == "__main__":
    unittest.main()
