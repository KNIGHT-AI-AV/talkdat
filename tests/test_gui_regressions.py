"""X-181: run the real-window regressions in their own interpreter.

These modules build REAL Tk windows and assert on what is actually mapped:

    tests/gui_buttons_on_screen.py   Stats and What's New had button rows that
                                     existed but occupied no space
    tests/gui_settings_persist.py    the theme never saved, and the six pill size
                                     fields could not hold a custom value
    tests/gui_micro_control_accessibility.py
                                     custom controls really construct with
                                     focus and single-invocation behavior

The original modules pass when run alone and errored six times inside the full suite, on
macOS, with `image "pyimageNNN" does not exist`.

The cause is Tk, not the tests. An image created without an explicit master binds
to `tk._default_root`. By the time these modules run, an earlier module in a
1600-test suite has already created a root, so `Overlay` builds a SECOND one and
every PhotoImage it makes is attached to the first. Clearing the pointer only
helps when the earlier root is dead; when it is alive, clearing it would be a lie
about somebody else's state.

So they get their own process. That is not a workaround for a flaky test, it is
the correct isolation for a library with one global interpreter pointer: the only
way to guarantee a clean `_default_root` is to be the first thing in the process
that touches Tk.

They are named `gui_*` rather than `test_*` so discovery does not also run them
in-process, which would reintroduce exactly the failure this avoids.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MODULES = (
    "tests.gui_flow_page_stack_scheduler",
    "tests.gui_buttons_on_screen",
    "tests.gui_settings_persist",
    "tests.gui_shell_page_sizing",
    "tests.gui_settings_local_model_lifecycle",
    "tests.gui_settings_page_dependency_lifecycle",
    "tests.gui_settings_lazy_failure",
    "tests.gui_utility_minimize_lifecycle",
    "tests.gui_utility_dwm_cloak_contracts",
    "tests.gui_scratchpad_saves",
    "tests.gui_micro_control_accessibility",
    "tests.gui_pill_panel_native_access_menu",
    "tests.gui_sidebar_overflow",
    "tests.gui_popup_reachability",
    "tests.gui_monitor_geometry_contracts",
)


class RealWindowRegressionsTests(unittest.TestCase):
    def _run(self, module: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "unittest", module, "-v"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=600,
        )

    def test_the_real_window_regressions_pass_in_a_clean_interpreter(self) -> None:
        for module in MODULES:
            with self.subTest(module=module):
                result = self._run(module)
                if result.returncode != 0:
                    self.fail(
                        f"{module} failed in its own interpreter:\n"
                        f"--- stdout ---\n{result.stdout[-3000:]}\n"
                        f"--- stderr ---\n{result.stderr[-3000:]}"
                    )

    def test_those_modules_are_not_also_collected_in_process(self) -> None:
        """Named gui_* on purpose. If one is renamed back to test_*, discovery
        runs it in-process against a foreign Tk root and it errors on images."""
        for module in MODULES:
            name = module.rsplit(".", 1)[-1]
            with self.subTest(module=name):
                self.assertFalse(
                    name.startswith("test_"),
                    f"{name} would be collected by discovery and run in-process",
                )
                self.assertTrue((ROOT / "tests" / f"{name}.py").exists(), f"{name}.py is missing")


if __name__ == "__main__":
    unittest.main()
