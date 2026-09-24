from __future__ import annotations

import ast
import gc
import inspect
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

import tkinter as tk
from PIL import Image

from knight_flow.ui.atelier_controls import (
    ATELIER_PALETTE_ROLES,
    AtelierButton,
    _resolve_palette,
)


MODULE_PATH = Path(__file__).resolve().parents[1] / "knight_flow" / "ui" / "atelier_controls.py"
SOURCE = MODULE_PATH.read_text(encoding="utf-8")

CANONICAL_PALETTE = {
    "canvas": "black",
    "surface": "gray20",
    "surface_hover": "gray25",
    "surface_pressed": "gray15",
    "surface_disabled": "gray18",
    "border": "gray45",
    "text": "white",
    "text_disabled": "gray70",
    "primary": "goldenrod2",
    "primary_hover": "goldenrod1",
    "primary_pressed": "goldenrod3",
    "on_primary": "black",
    "on_primary_disabled": "gray70",
    "focus": "SkyBlue1",
    "shadow": "gray5",
    "top_highlight": "gray55",
    "primary_highlight": "lightgoldenrod1",
}


class AtelierButtonContractTests(unittest.TestCase):
    def test_is_a_native_button_with_the_onboarding_constructor_shape(self) -> None:
        self.assertTrue(issubclass(AtelierButton, tk.Button))
        self.assertFalse(issubclass(AtelierButton, tk.Canvas))
        signature = inspect.signature(AtelierButton.__init__)
        expected = ("master", "text", "command", "palette", "primary", "min_width", "scale")
        for name in expected:
            self.assertIn(name, signature.parameters)
        self.assertEqual(signature.parameters["primary"].default, False)
        self.assertIsNone(signature.parameters["min_width"].default)

    def test_exact_scaled_design_heights(self) -> None:
        self.assertEqual(AtelierButton.design_height(primary=True, scale=1.0), 44)
        self.assertEqual(AtelierButton.design_height(primary=False, scale=1.0), 40)
        self.assertEqual(AtelierButton.design_height(primary=True, scale=1.25), 55)
        self.assertEqual(AtelierButton.design_height(primary=False, scale=1.25), 50)
        with self.assertRaises(ValueError):
            AtelierButton.design_height(primary=True, scale=0)

    def test_palette_resolver_returns_every_canonical_semantic_role(self) -> None:
        self.assertEqual(set(_resolve_palette(CANONICAL_PALETTE)), set(ATELIER_PALETTE_ROLES))

    def test_existing_theme_role_aliases_resolve_without_embedded_colors(self) -> None:
        existing = {
            "bg": "black",
            "panel": "gray10",
            "surface": "gray20",
            "field": "gray15",
            "stroke": "gray40",
            "text": "white",
            "muted": "gray70",
            "accent": "goldenrod2",
            "accent2": "turquoise2",
            "select": "gray25",
            "button": "gray18",
        }
        resolved = _resolve_palette(existing)
        self.assertEqual(resolved["canvas"], existing["bg"])
        self.assertEqual(resolved["primary"], existing["accent"])
        self.assertEqual(resolved["focus"], existing["accent2"])

    def test_source_owns_no_literal_hex_colors_or_canvas_actions(self) -> None:
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", SOURCE))
        tree = ast.parse(SOURCE)
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("after_idle", called_attributes)
        self.assertNotIn("create_image", called_attributes)
        self.assertNotIn("create_text", called_attributes)
        self.assertNotIn("create_polygon", called_attributes)
        self.assertIn("after", called_attributes)
        self.assertIn("after_cancel", called_attributes)

    def test_keyboard_and_pointer_binding_shape_is_explicit(self) -> None:
        tree = ast.parse(SOURCE)
        sequences = {
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "bind"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        }
        self.assertTrue(
            {
                "<KeyPress-Return>",
                "<KeyRelease-Return>",
                "<KeyPress-space>",
                "<KeyRelease-space>",
                "<FocusIn>",
                "<FocusOut>",
                "<Enter>",
                "<Leave>",
                "<ButtonPress-1>",
                "<ButtonRelease-1>",
            }.issubset(sequences)
        )

    def test_config_is_the_same_button_compatible_method(self) -> None:
        self.assertIs(AtelierButton.config, AtelierButton.configure)
        self.assertIn("text", inspect.getsource(AtelierButton.configure))
        self.assertIn("state", inspect.getsource(AtelierButton.configure))
        self.assertIn("text", inspect.getsource(AtelierButton.cget))
        self.assertIn("state", inspect.getsource(AtelierButton.cget))


def _usable_root() -> tuple[tk.Tk | None, Exception | None]:
    try:
        root = tk.Tk()
        root.withdraw()
        return root, None
    except Exception as error:
        return None, error


_ROOT, _ROOT_ERROR = _usable_root()
if _ROOT is not None:
    _ROOT.destroy()
    _ROOT = None
    # Tk objects are cyclic. Collect the destroyed probe on the interpreter
    # thread now, before a later audio-spool worker can become the thread that
    # happens to trigger Python's cyclic collector.
    gc.collect()


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class AtelierButtonTkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()

        def destroy_on_tk_thread() -> None:
            root = self.root
            self.root = None  # type: ignore[assignment]
            root.destroy()
            # Tcl panics instead of raising if a dead Tk object's cycle is
            # collected by a background thread. End every test with no dead Tk
            # cycle available for the following threaded audio tests to find.
            gc.collect()

        self.addCleanup(destroy_on_tk_thread)

    def test_runtime_api_geometry_managers_states_and_keyboard_activation(self) -> None:
        calls: list[str] = []
        button = AtelierButton(
            self.root,
            text="Continue",
            command=lambda: calls.append("called"),
            palette=CANONICAL_PALETTE,
            primary=True,
            min_width=120,
            scale=1.25,
        )
        self.assertEqual(button.cget("text"), "Continue")
        self.assertEqual(button.cget("state"), tk.NORMAL)
        self.assertEqual(button.configure("text")[-1], "Continue")
        self.assertEqual(button.configure("state")[-1], tk.NORMAL)
        self.assertIn("text", button.configure())
        self.assertIn("state", button.configure())
        self.assertEqual(button.winfo_class(), "Button")
        self.assertEqual(int(float(button.cget("height"))), 55)
        self.assertEqual(str(button.cget("takefocus")), "1")
        self.assertEqual(button.cget("cursor"), "hand2")
        self.assertGreaterEqual(button._background_image.width(), 1)
        self.assertGreaterEqual(button._background_image.height(), 1)

        button.pack()
        button.pack_forget()
        button.grid(row=0, column=0)
        button.grid_forget()

        # A withdrawn root does not dispatch generated key events on every Tk
        # build. The contract test above proves the actual bindings; exercise
        # the handlers directly to prove repeat suppression and release-only
        # activation without placing a test window on screen.
        return_key = SimpleNamespace(keysym="Return")
        button._on_keyboard_press(return_key)  # type: ignore[arg-type]
        button._on_keyboard_press(return_key)  # auto-repeat is ignored
        button._on_keyboard_release(return_key)  # type: ignore[arg-type]
        space_key = SimpleNamespace(keysym="space")
        button._on_keyboard_press(space_key)  # type: ignore[arg-type]
        button._on_keyboard_release(space_key)  # type: ignore[arg-type]
        self.assertEqual(calls, ["called", "called"])

        button.configure(text="Finish", state=tk.DISABLED)
        self.assertEqual(button.cget("text"), "Finish")
        self.assertEqual(button.cget("state"), tk.DISABLED)
        self.assertEqual(button.cget("cursor"), "")
        button._on_keyboard_press(return_key)  # type: ignore[arg-type]
        button._on_keyboard_release(return_key)  # type: ignore[arg-type]
        button.invoke()
        self.assertEqual(calls, ["called", "called"])

        button.config(state=tk.NORMAL)
        self.assertEqual(button.cget("cursor"), "hand2")
        button.invoke()
        self.assertEqual(calls, ["called", "called", "called"])

    def test_identical_visual_signature_does_not_rebuild_the_tk_image(self) -> None:
        button = AtelierButton(
            self.root,
            text="Continue",
            command=lambda: None,
            palette=CANONICAL_PALETTE,
            primary=True,
            min_width=137,
            scale=1.0,
        )
        button.pack()
        self.root.update_idletasks()
        self.root.update()
        button._settle_resize_redraw()
        original = button._background_image
        signature = button._last_render_signature

        for _ in range(20):
            button._redraw()

        self.assertIs(button._background_image, original)
        self.assertEqual(button._last_render_signature, signature)

    def test_configure_storm_is_frame_coalesced_and_final_size_settles(self) -> None:
        button = AtelierButton(
            self.root,
            text="Resize",
            command=lambda: None,
            palette=CANONICAL_PALETTE,
            primary=False,
            min_width=141,
            scale=1.0,
        )
        button.pack()
        self.root.update_idletasks()
        self.root.update()

        for attribute in ("_resize_frame_after", "_resize_settle_after"):
            receipt = getattr(button, attribute)
            if receipt is not None:
                button.after_cancel(receipt)
                setattr(button, attribute, None)

        scheduled: dict[str, tuple[int, object]] = {}
        cancelled: list[str] = []
        serial = 0

        def schedule(delay: int, callback: object) -> str:
            nonlocal serial
            serial += 1
            receipt = f"timer-{serial}"
            scheduled[receipt] = (delay, callback)
            return receipt

        def cancel(receipt: str) -> None:
            cancelled.append(receipt)
            scheduled.pop(receipt, None)

        button.after = schedule  # type: ignore[method-assign]
        button.after_cancel = cancel  # type: ignore[method-assign]
        calls = 0
        original_redraw = button._redraw

        def counted_redraw() -> None:
            nonlocal calls
            calls += 1
            original_redraw()

        button._redraw = counted_redraw  # type: ignore[method-assign]
        for index in range(120):
            event = SimpleNamespace(width=220 + index, height=40 + (index % 2))
            button._on_resize(
                event  # type: ignore[arg-type]
            )

        self.assertEqual(calls, 0, "Configure must not synchronously rasterize")
        live = list(scheduled.values())
        self.assertEqual(sum(delay == button.RESIZE_FRAME_MS for delay, _ in live), 1)
        self.assertEqual(sum(delay == button.RESIZE_SETTLE_MS for delay, _ in live), 1)
        self.assertGreaterEqual(len(cancelled), 119)

        frame_receipt = button._resize_frame_after
        self.assertIsNotNone(frame_receipt)
        _delay, frame_callback = scheduled.pop(str(frame_receipt))
        frame_callback()  # type: ignore[operator]
        self.assertEqual(calls, 1)
        self.assertIsNone(button._resize_frame_after)

        # Settle uses the actual final widget geometry and cancels any pending
        # frame.  Signature deduplication keeps this correctness pass cheap if
        # the frame already landed on that exact size.
        settle_receipt = button._resize_settle_after
        self.assertIsNotNone(settle_receipt)
        _delay, settle_callback = scheduled.pop(str(settle_receipt))
        settle_callback()  # type: ignore[operator]
        self.assertEqual(calls, 2)
        self.assertIsNone(button._resize_settle_after)
        self.assertIsNone(button._pending_resize)

    def test_plain_pil_skin_cache_is_bounded_but_tk_images_remain_per_button(self) -> None:
        AtelierButton._skin_cache.clear()
        self.addCleanup(AtelierButton._skin_cache.clear)
        first = AtelierButton(
            self.root,
            text="Same",
            command=lambda: None,
            palette=CANONICAL_PALETTE,
            min_width=133,
        )
        second = AtelierButton(
            self.root,
            text="Same",
            command=lambda: None,
            palette=CANONICAL_PALETTE,
            min_width=133,
        )
        self.assertIsNot(first._background_image, second._background_image)
        self.assertEqual(len(AtelierButton._skin_cache), 1)

        for index in range(AtelierButton.SKIN_CACHE_LIMIT + 7):
            signature = ("bounded-test", index)
            AtelierButton._remember_skin(signature, Image.new("RGBA", (1, 1)))
        self.assertEqual(len(AtelierButton._skin_cache), AtelierButton.SKIN_CACHE_LIMIT)
        self.assertNotIn(("bounded-test", 0), AtelierButton._skin_cache)


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(_ROOT_ERROR is not None, f"no usable Tk display: {_ROOT_ERROR}")
class AtelierButtonHitAreaTests(unittest.TestCase):
    """A press must survive the hand that made it.

    Two defects the same size, found together (X-536). Releasing one pixel past
    the drawn border cancelled the action, which reads as a dead button and
    penalises exactly the people least able to hold a pointer still. And nothing
    on the button changed while the pointer was dragged away, so the affordance
    that says "let go here and nothing happens" only appeared after letting go,
    when it was no longer a choice.
    """

    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()

        def destroy_on_tk_thread() -> None:
            root = self.root
            self.root = None  # type: ignore[assignment]
            root.destroy()
            gc.collect()

        self.addCleanup(destroy_on_tk_thread)
        self.calls: list[str] = []
        self.button = AtelierButton(
            self.root,
            text="Continue",
            command=lambda: self.calls.append("invoked"),
            palette=CANONICAL_PALETTE,
            primary=True,
            scale=1.0,
        )
        self.button.pack()
        self.root.update_idletasks()

    def _release(self, x: int, y: int) -> None:
        self.button._on_press(SimpleNamespace(x=1, y=1))
        self.button._on_release(SimpleNamespace(x=x, y=y))

    def test_a_release_just_outside_the_border_still_counts(self) -> None:
        width = self.button.winfo_width()
        height = self.button.winfo_height()
        for x, y, where in (
            (-3, height // 2, "just left"),
            (width + 3, height // 2, "just right"),
            (width // 2, -3, "just above"),
            (width // 2, height + 3, "just below"),
        ):
            self.calls.clear()
            self._release(x, y)
            self.assertEqual(self.calls, ["invoked"], f"released {where} of the edge")

    def test_a_release_well_clear_of_the_button_does_not(self) -> None:
        """Slop forgives a slip. It must not swallow a deliberate cancel."""

        width = self.button.winfo_width()
        beyond = width + self.button.HIT_SLOP * 4
        self.calls.clear()
        self._release(beyond, self.button.winfo_height() // 2)
        self.assertEqual(self.calls, [])

    def test_the_button_lets_go_visually_while_the_pointer_is_still_down(self) -> None:
        self.button._on_press(SimpleNamespace(x=1, y=1))
        self.assertTrue(self.button._pressed, "press must light the button")

        far = self.button.winfo_width() + self.button.HIT_SLOP * 4
        self.button._on_drag(SimpleNamespace(x=far, y=1))
        self.assertFalse(
            self.button._pressed,
            "dragging away must release the button before the pointer is lifted",
        )

        self.button._on_drag(SimpleNamespace(x=2, y=2))
        self.assertTrue(
            self.button._pressed,
            "dragging back must re-arm it -- cancel is reversible, like a real button",
        )

        self.calls.clear()
        self.button._on_release(SimpleNamespace(x=2, y=2))
        self.assertEqual(self.calls, ["invoked"])

    def test_a_disabled_button_ignores_the_whole_gesture(self) -> None:
        self.button.configure(state=tk.DISABLED)
        self.calls.clear()
        self.button._on_press(SimpleNamespace(x=1, y=1))
        self.button._on_drag(SimpleNamespace(x=1, y=1))
        self.button._on_release(SimpleNamespace(x=1, y=1))
        self.assertEqual(self.calls, [])
        self.assertFalse(self.button._pressed)
