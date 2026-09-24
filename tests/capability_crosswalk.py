"""X-157: read every capability the app exposes, straight from the source.

Shared by the crosswalk test and by scripts/build_capability_manifest.py, so
the baseline and the check can never drift apart by being written twice.

Everything here parses source text rather than importing the modules. The
settings console and the tray both pull in tkinter and pystray at import time,
which cannot be relied on in a headless test run -- and the point of this file
is to work everywhere, every time, not only on a machine with a display.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"
TRAY = ROOT / "knight_flow" / "tray.py"
APP = ROOT / "knight_flow" / "app.py"
ONBOARDING = ROOT / "knight_flow" / "onboarding.py"
CONSOLE = ROOT / "knight_flow" / "ui" / "flow_console.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def pill_menu_actions() -> list[str]:
    """Action ids in the pill's right-click menu, including the side panel.

    X-339 moved the six occasional rows out of the flat list and into
    _context_menu_feature_rows (the Features SIDE PANEL). They are still
    real, reachable destinations, so the harvest reads both bodies.
    """
    src = _read(OVERLAY)
    feature_start = src.index("def _context_menu_feature_rows")
    feature_end = src.index("def ", feature_start + 10)
    start = src.index("def _context_menu_default_rows")
    end = src.index("SHELL_PAGES", start)
    body = src[start:end] + src[feature_start:feature_end]
    return sorted(set(re.findall(r'\(\s*"([a-z_0-9]+)",\s*\n?\s*"', body)))


def tray_commands() -> list[str]:
    """Callback keys the tray menu invokes."""
    return sorted(set(re.findall(r'self\._call\("([a-z_0-9]+)"\)', _read(TRAY))))


def tray_labels() -> list[str]:
    """Visible tray labels, so a rename is visible in the diff too."""
    src = _read(TRAY)
    labels = set(re.findall(r'pystray\.MenuItem\("([^"]+)"', src))
    # The two dynamic labels are built by methods, not literals.
    labels.update({"Pause dictation", "Resume dictation", "Check for updates"})
    return sorted(labels)


def relocated_tools() -> list[str]:
    """The five items Settings -> Tools carries."""
    src = _read(OVERLAY)
    start = src.index("RELOCATED_TOOLS = (")
    # Close on the dedented ")" that ends the class attribute, not on the first
    # ")" inside it -- the tuple holds tuples, so the naive search stops after
    # a single entry and the guard silently protects one tool instead of five.
    end = src.index("\n    )", start)
    return sorted(set(re.findall(r'\("([a-z_0-9]+)",\s*"', src[start:end])))


def shell_pages() -> list[str]:
    """Windows the shell can open, by id."""
    src = _read(OVERLAY)
    start = src.index("SHELL_PAGES = frozenset({")
    end = src.index("})", start)
    return sorted(set(re.findall(r'"([a-z_0-9]+)"', src[start:end])))


def settings_pages() -> list[str]:
    return [m for m in re.findall(r'make_scroll_tab\("([^"]+)"\)', _read(OVERLAY))]


def settings_sections() -> list[str]:
    """Every titled section, as "page_var -> Title"."""
    found = re.findall(r'section\(([a-z_]+), "([^"]+)"\)', _read(OVERLAY))
    return sorted({f"{page} -> {title}" for page, title in found})


def rail_sections() -> list[str]:
    """The keys the settings rail advertises."""
    tree = ast.parse(_read(CONSOLE))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "FLOW_CONSOLE_SECTIONS" for t in node.targets
        ):
            return [e.elts[0].value for e in node.value.elts if isinstance(e, ast.Tuple) and e.elts]
    raise AssertionError("FLOW_CONSOLE_SECTIONS not found")


def app_commands() -> list[str]:
    """Every key the overlay/tray callback registry answers to.

    Bound to the `callbacks = {...}` literal by AST rather than matched by a
    regex over the whole file.

    The regex version matched any `"name": self.thing` at eight-plus spaces of
    indent ANYWHERE in app.py, so it swept up dict FIELDS that are not commands.
    An exhaustive sweep of the manifest identified several: `downloading_model`
    (a key in a progress-message map), `in_progress` (a field of
    `license_activation_status`), `language` (a field of `status_snapshot`),
    `onboarding_incomplete`. Each then sat in the frozen capability list as a
    command nothing could ever invoke.

    That matters beyond tidiness. The manifest is the contract asserting no
    capability was lost in a refactor, and a contract padded with entries that
    were never capabilities cannot do that job honestly: it inflates the count
    that is supposed to prove nothing went missing.

    `rail_sections` already parses its source with AST; this brings app_commands
    into line.
    """
    tree = ast.parse(_read(APP))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "callbacks" for t in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        keys = [
            key.value
            for key in node.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        ]
        if keys:
            return sorted(set(keys))
    raise AssertionError("the callbacks registry literal was not found in app.py")


def onboarding_steps() -> list[str]:
    """Step ids in flow order, Windows build (macOS adds 'permissions')."""
    src = _read(ONBOARDING)
    return re.findall(r'OnboardingStep\(\s*(?:#[^\n]*\n\s*)*"([a-z_]+)",', src)


def snapshot() -> dict[str, list[str]]:
    """The whole reachable surface, in one comparable shape."""
    return {
        "pill_menu_actions": pill_menu_actions(),
        "tray_commands": tray_commands(),
        "tray_labels": tray_labels(),
        "relocated_tools": relocated_tools(),
        "shell_pages": shell_pages(),
        "settings_pages": settings_pages(),
        "settings_sections": settings_sections(),
        "rail_sections": rail_sections(),
        "app_commands": app_commands(),
        "onboarding_steps": onboarding_steps(),
    }
