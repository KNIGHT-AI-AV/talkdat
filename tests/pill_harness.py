"""A real Pill for the interaction-grid tests (X-619 onward).

Builds a real Overlay and drives it with synthetic presses and releases, the
way Tk would deliver a hand's click. Imported by test modules that run only
through scripts/run_tests_offscreen.py, so nothing appears on anyone's screen
(gui_offscreen parks and blanks every window as well, belt and braces).

Not named test_* so discovery does not collect it as a module of its own.
"""
from __future__ import annotations

import copy
import time
from typing import Any, Callable

from knight_flow.config import DEFAULT_CONFIG
from tests import gui_offscreen  # noqa: F401  (X-164: never on a human's screen)


def forget_default_root() -> None:
    """Tk binds every image made without a master to tkinter's default root.
    A root left behind by an earlier module would own this module's images
    ("image pyimageNN doesn't exist"), so each test starts and ends without
    one, as test_the_pill_answers_success_and_error does."""
    import tkinter

    existing = getattr(tkinter, "_default_root", None)
    try:
        alive = existing is not None and bool(existing.winfo_exists())
    except Exception:
        alive = False
    if not alive:
        tkinter._default_root = None  # type: ignore[attr-defined]


def pump(root: Any, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        root.update()
        time.sleep(0.01)


class Counter:
    """A callback that counts its calls."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls += 1


def build_overlay(callbacks: dict[str, Callable[..., Any]] | None = None, *, reduce_motion: bool = False,
                  scale: float = 1.5, settle: float = 0.4) -> Any:
    from knight_flow.overlay import Overlay
    from tests.tk_support import acquire_root

    forget_default_root()
    config = copy.deepcopy(DEFAULT_CONFIG)
    config.setdefault("ui", {})["scale"] = scale
    config["ui"]["reduce_motion"] = reduce_motion
    # macOS: one Tk root per process, ever (tests/tk_support). A fresh tk.Tk()
    # per test landed each Overlay's images in the previous test's now-dead
    # interpreter ("image pyimageNN does not exist"); acquire_root() hands out
    # the one shared root there instead, exactly as
    # test_the_pill_answers_success_and_error.py does.
    overlay = Overlay(config, callbacks=dict(callbacks or {}), root=acquire_root())
    pump(overlay.root, settle)
    return overlay


def destroy_overlay(overlay: Any) -> None:
    if overlay is None:
        return
    from tests.tk_support import release_root

    try:
        release_root(overlay._tk_root)
    except Exception:
        pass
    forget_default_root()


def canvas_point(overlay: Any, x: int, y: int) -> tuple[int, int, int, int]:
    """(x, y, root_x, root_y) for a point in the Pill canvas's own pixels."""
    canvas = overlay.canvas
    return x, y, int(canvas.winfo_rootx()) + x, int(canvas.winfo_rooty()) + y


def press(overlay: Any, x: int, y: int, *, button: int = 1) -> None:
    cx, cy, rx, ry = canvas_point(overlay, x, y)
    overlay.canvas.event_generate(f"<ButtonPress-{button}>", x=cx, y=cy, rootx=rx, rooty=ry)


def release(overlay: Any, x: int, y: int, *, button: int = 1) -> None:
    cx, cy, rx, ry = canvas_point(overlay, x, y)
    overlay.canvas.event_generate(f"<ButtonRelease-{button}>", x=cx, y=cy, rootx=rx, rooty=ry)


def click(overlay: Any, x: int, y: int) -> None:
    press(overlay, x, y)
    release(overlay, x, y)


def body_point(overlay: Any) -> tuple[int, int]:
    """A point well inside the Pill body and far from the update dot."""
    return max(4, int(overlay.current_width) // 5), max(2, int(overlay.current_height) // 2)
