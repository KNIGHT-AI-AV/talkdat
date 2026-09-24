from __future__ import annotations

import re
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py").read_text(encoding="utf-8")


def update_window_source() -> str:
    """The body of the update window builder."""
    start = SOURCE.index("on_install: Callable[..., None],")
    end = SOURCE.index("def _history_window_text", start)
    return SOURCE[start:end]


class InstallButtonIsReachableTests(unittest.TestCase):
    """The update window shipped with no visible way to install the update.

    Tk gives the whole remaining cavity to the first widget packed with
    expand=True. The notes area was packed that way before the button row, so
    the buttons were allotted no space and Tk silently never drew them -- no
    exception, no warning, just a window offering an update and no means of
    taking it. Verified directly: with the old order winfo_ismapped() on the
    install button returns False; with this order it returns True.

    These assert the ordering contract rather than pixels, because the failure
    was an ordering mistake and would return the same way.
    """

    def test_the_buttons_are_packed_before_the_notes_expand(self) -> None:
        body = update_window_source()
        buttons_pack = body.index("buttons.pack(")
        notes_pack = body.index("notes_frame.pack(")
        self.assertLess(
            buttons_pack,
            notes_pack,
            "the notes claim the cavity first and the buttons never get drawn",
        )

    def test_the_button_row_is_anchored_to_the_window_bottom(self) -> None:
        body = update_window_source()
        match = re.search(r"buttons\.pack\(([^)]*)\)", body)
        assert match is not None
        self.assertIn('side="bottom"', match.group(1),
                      "without an explicit anchor the row queues behind expanding widgets")

    def test_the_notes_are_the_only_thing_that_expands(self) -> None:
        body = update_window_source()
        match = re.search(r"notes_frame\.pack\(([^)]*)\)", body)
        assert match is not None
        self.assertIn("expand=True", match.group(1))

    def test_an_install_button_exists_and_is_wired_to_something(self) -> None:
        body = update_window_source()
        self.assertIn('install_button = ttk.Button', body)
        self.assertIn("install_button.configure(command=start_install)", body)
        self.assertIn("on_install(", body)

    def test_the_install_button_is_shown_whenever_there_is_an_installer(self) -> None:
        body = update_window_source()
        self.assertIn('if data.get("has_installer"):', body)
        self.assertIn("install_button.pack(", body)

    def test_security_transaction_locks_every_window_exit_route(self) -> None:
        body = update_window_source()
        self.assertIn("window._navigation_locked = bool(locked)", body)
        self.assertIn("window._close_locked = bool(locked)", body)
        self.assertIn('window.bind("<Escape>", request_close)', body)
        self.assertIn('window.protocol("WM_DELETE_WINDOW", request_close)', body)
        self.assertIn("set_install_lock(False)", body)

    def test_metadata_and_security_status_wrap_with_the_live_window(self) -> None:
        body = update_window_source()
        self.assertIn("version_label.configure(wraplength=wrap)", body)
        self.assertIn("status_label.configure(wraplength=wrap)", body)
        self.assertIn('window.bind("<Configure>", wrap_update_metadata', body)


class ReleaseNotesAreRenderedTests(unittest.TestCase):
    """GitHub Markdown was inserted verbatim into a plain Text widget, so the
    window showed "### Pricing" and "- item" to the person deciding whether to
    install. readable_release_notes existed and was tested the whole time -- it
    was simply never called on this path."""

    def test_the_notes_go_through_the_renderer(self) -> None:
        body = update_window_source()
        self.assertIn("readable_release_notes(data.get(\"release_notes\"", body)

    def test_the_raw_field_is_not_inserted_directly(self) -> None:
        body = update_window_source()
        self.assertNotIn('notes.insert("1.0", str(data.get("release_notes"', body)


if __name__ == "__main__":
    unittest.main()
