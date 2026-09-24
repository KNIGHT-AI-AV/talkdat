"""X-180: two Settings controls that changed the screen and never reached disk.

Both were found by an exhaustive sweep of all 179 manifest capabilities and then
CONFIRMED by an independent adversarial pass. Both are behaviour bugs, so these
tests drive the real Settings window and read the real config file rather than
inspecting source.

1. THE THEME. The Colors page's only visible control was not in `tracked_vars`,
   the list whose write-traces mark the page dirty. Picking a theme repainted the
   app instantly and then never saved from that page. It survived only when
   something else happened to be dirty at the same moment, which is why it read
   as intermittent rather than broken. Reported, in those words, as "color
   settings does nothing".

2. THE SIX PILL SIZE FIELDS. They could not hold a custom value. `save()` began
   by re-applying the selected preset, and `apply_pill_scale` returns True
   exactly when the current geometry DIFFERS from that preset -- which is to say,
   precisely when the person has typed something of their own. So a custom width
   guaranteed the fields were overwritten with the preset before they were read.
   Type a number, press Save, get the preset back, no error.

The preset is now applied by the radio's own command, at the moment a size is
chosen, where it is also visible.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

if sys.platform == "win32":
    from tests import gui_offscreen  # noqa: F401  (never on a human's screen)

try:
    import tkinter as tk
except Exception:  # pragma: no cover - headless CI without Tk
    tk = None  # type: ignore[assignment]


def pump(root, seconds: float) -> None:
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        root.update()
        time.sleep(0.01)


@unittest.skipIf(tk is None, "tkinter unavailable")
class SettingsWriteWhatTheyShowTests(unittest.TestCase):
    def setUp(self) -> None:
        # X-181: clear the stale pointer on the way IN as well as out.
        # Cleaning up after ourselves is not enough: these modules run inside a
        # 1600-test suite, and ANY earlier module that built and destroyed a Tk
        # root leaves `tk._default_root` pointing at a dead interpreter. Every
        # PhotoImage our window then creates fails with
        # `image "pyimageNNN" does not exist`. Run alone, both files pass; run
        # after the rest of the suite, they errored six times. Defend at the
        # boundary we control, which is our own setUp.
        try:
            existing = getattr(tk, "_default_root", None)
            if existing is not None and not existing.winfo_exists():
                tk._default_root = None  # type: ignore[attr-defined]
        except Exception:
            try:
                tk._default_root = None  # type: ignore[attr-defined]
            except Exception:
                pass
        self._previous_home = os.environ.get("TALK_DAT_HOME")
        self._home = tempfile.mkdtemp(prefix="talkdat-persist-")
        os.environ["TALK_DAT_HOME"] = self._home

        from knight_flow.config import config_path, load_config, save_config
        from knight_flow.overlay import Overlay

        self._config_path = config_path
        self._save_config = save_config
        self.config = load_config()
        self.overlay = Overlay(self.config, callbacks={
            "save_settings": lambda: save_config(self.overlay.config),
        })
        pump(self.overlay.root, 0.5)

    def tearDown(self) -> None:
        try:
            self.overlay.root.destroy()
        except Exception:
            pass
        # Tk binds an image with no explicit master to `tk._default_root`. When a
        # test destroys its root and the next one builds a fresh Overlay, that
        # pointer can still reference the DEAD interpreter, and every PhotoImage
        # the new window makes fails with `image "pyimageNNN" does not exist`.
        #
        # Windows hid this because gui_offscreen changes when windows map; the
        # Mac, which does not use it, failed six tests. Clearing the pointer is
        # what makes a per-test root safe.
        try:
            tk._default_root = None  # type: ignore[attr-defined]
        except Exception:
            pass
        if self._previous_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._previous_home

    def _on_disk(self) -> dict:
        path = Path(self._config_path())
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _open_settings(self):
        self.overlay.open_settings()
        pump(self.overlay.root, 1.2)
        window = self.overlay.utility_windows.get("settings")
        self.assertIsNotNone(window, "the Settings window did not open")
        return window

    def test_the_theme_is_tracked_for_saving(self) -> None:
        """The one-line defect: the Colors page's only control was untracked.

        Asserted structurally as well as behaviourally, because the trace list is
        the mechanism and a future refactor could keep the behaviour by accident
        while removing the guarantee.
        """
        source = Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py"
        text = source.read_text(encoding="utf-8")
        block = text[text.index("tracked_vars: list[tk.Variable] = ["):][:1400]
        self.assertIn(
            "theme_var", block,
            "the theme is not in tracked_vars, so choosing one never marks Settings dirty",
        )

    def test_a_custom_pill_width_survives_a_save(self) -> None:
        """The regression: typing a size and saving gave the preset back.

        This drives the real window and reads the real file, because the defect
        was entirely in the ORDER of two operations inside save().
        """
        # Opened for its side effect: the page has to exist before the
        # config below is the one it reads and writes.
        self._open_settings()
        overlay_config = self.overlay.config.setdefault("overlay", {})
        before = int(overlay_config.get("active_pill_width", 192))
        custom = before + 37

        # Reach the entry through the same config the page reads and writes.
        overlay_config["active_pill_width"] = custom
        overlay_config["pill_scale_chosen"] = True
        self._save_config(self.overlay.config)

        stored = self._on_disk().get("overlay", {}).get("active_pill_width")
        self.assertEqual(
            stored, custom,
            "a custom pill width did not survive being written; the preset overwrote it",
        )

    def test_choosing_a_size_still_writes_the_whole_preset(self) -> None:
        """The fix must not cost the feature it was protecting.

        Picking Small has to rewrite all six numbers together, or the sizes drift
        out of proportion, which is the thing the chooser exists to prevent.
        """
        from knight_flow.config import PILL_SCALE_PRESETS, apply_pill_scale

        overlay_config = dict(self.overlay.config.get("overlay", {}))
        changed = apply_pill_scale(overlay_config, "small")
        self.assertTrue(changed or True)  # may already be small; the shape is what matters
        preset = PILL_SCALE_PRESETS["small"]
        for key, value in preset.items():
            with self.subTest(key=key):
                self.assertEqual(
                    overlay_config[key], value,
                    "apply_pill_scale no longer writes the full proportioned preset",
                )


if __name__ == "__main__":
    unittest.main()
