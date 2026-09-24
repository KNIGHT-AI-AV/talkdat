from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Two build paths, two sources of truth -- deliberately.
#
# The INSTALLER script builds its small Tk entries with CLI flags, so its
# exclusions live in the script. The APP is built FROM the curated
# "Talk Dat!.spec" (spec-mode never rewrites the spec), because building the
# app via CLI is exactly how the curated spec got silently clobbered on
# 2026-08-08 -- taking the cryptography collection with it. So the app's
# exclusions are asserted in the SPEC, and the script is asserted to build
# from it and to carry no CLI exclusions of its own that could drift.
INSTALLER_SCRIPT = "build-custom-installer.ps1"
# Each platform is built from its own spec. The Windows one is committed as of
# 2026-08-08; the macOS build has always used TalkDat-mac.spec, and asserting
# the Windows filename here would fail on a Mac for the wrong reason.
APP_SPEC = "TalkDat-mac.spec" if sys.platform == "darwin" else "Talk Dat!.spec"
# The script that consumes it. Each platform builds from its own pair, and
# asserting the Windows pair on a Mac would fail for the wrong reason.
APP_BUILD_SCRIPT = "build-mac.sh" if sys.platform == "darwin" else "build-exe.ps1"

# Packages that must never reach a build, with the reason each one tried to.
BANNED = {
    "cv2": (
        "OpenCV is 109 MB in the virtualenv, arriving through pyautogui -> "
        "pyscreeze for locateOnScreen matching this product never performs. "
        "Excluding it was measured at exactly 0 MB off the executable -- "
        "PyInstaller's analysis already left it out -- so this is defensive "
        "rather than a saving, and stops a future dependency reintroducing it."
    ),
}

# openwakeword 0.6 imports these during initialization. The installer UI does
# not use wake recognition; the application does and must not exclude them.
WAKE_IMPORTS = {"scipy", "sklearn"}


class NothingHeavyGetsBundledTests(unittest.TestCase):
    """Every megabyte is a download an unsigned installer has to justify.

    The installer is 210 MB from a publisher Windows does not recognise, so
    size is not a tidiness concern -- it is the first thing standing between a
    prospect and the product, right next to a SmartScreen warning.

    Worth recording what this did *not* find. Importing knight_flow.app from
    source takes 1,091 ms and 387 ms of that is pyautogui pulling in cv2 --
    but excluding cv2 changed the built executable by 0 MB, because
    PyInstaller was already leaving it out. The 387 ms is a development cost,
    not something a customer pays, and measuring the venv is not measuring the
    build. These exclusions are a ratchet against future weight rather than a
    saving already banked.
    """

    def excludes(self, script: str) -> list[str]:
        text = (ROOT / script).read_text(encoding="utf-8")
        return re.findall(r'"--exclude-module",\s*"([^"]+)"', text)

    def spec_excludes(self) -> list[str]:
        text = (ROOT / APP_SPEC).read_text(encoding="utf-8")
        match = re.search(r"excludes=\[([^\]]*)\]", text)
        return re.findall(r'"([^"]+)"', match.group(1)) if match else []

    def test_every_build_script_excludes_the_heavy_unused_packages(self) -> None:
        for package, why in BANNED.items():
            with self.subTest(script=INSTALLER_SCRIPT, package=package):
                self.assertIn(
                    package, self.excludes(INSTALLER_SCRIPT),
                    f"{INSTALLER_SCRIPT} would bundle {package}. {why}",
                )
            with self.subTest(script=APP_SPEC, package=package):
                self.assertIn(
                    package, self.spec_excludes(),
                    f"{APP_SPEC} would bundle {package}. {why}",
                )

    def test_the_app_builds_from_the_curated_spec_and_only_from_it(self) -> None:
        """This asserted the OPPOSITE until 2026-08-08 -- 'a spec is a build
        artifact' was true while the app built via CLI flags, and that CLI
        path is how the curated spec got silently regenerated, dropping the
        cryptography collection a shipped build depends on. The spec is now
        the single source of truth: tracked in git, invoked by name, and the
        script may carry no exclusions of its own to drift."""
        script = (ROOT / APP_BUILD_SCRIPT).read_text(encoding="utf-8-sig")
        self.assertIn(APP_SPEC, script, f"{APP_BUILD_SCRIPT} must build from the curated spec")
        self.assertNotIn("--exclude-module", script,
                         "app exclusions live in the spec; a second copy here would drift")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        # Both specs are tracked, each with its own negation, for the same
        # reason: an untracked spec is how the clobber went unnoticed.
        self.assertIn(f"!{APP_SPEC}", gitignore, "an untracked spec is how the clobber went unnoticed")

    def test_the_product_really_does_not_use_opencv(self) -> None:
        """The justification for excluding it, asserted rather than assumed.

        If a screenshot feature is ever added this test fails, which is the
        right moment to reconsider -- rather than discovering it as a crash in
        a shipped build.
        """
        offenders = []
        for path in (ROOT / "knight_flow").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for marker in ("import cv2", "locateOnScreen", "locateCenterOnScreen", "pyautogui.screenshot"):
                if marker in source:
                    offenders.append(f"{path.name}: {marker}")
        self.assertEqual(offenders, [], f"something now needs OpenCV: {offenders}")

    def test_the_two_build_paths_agree(self) -> None:
        """Them drifting apart is how the installer ends up carrying something
        the portable build does not, which nobody notices until a download is
        mysteriously larger."""
        sets = {INSTALLER_SCRIPT: set(self.excludes(INSTALLER_SCRIPT)), APP_SPEC: set(self.spec_excludes())}
        first = sets[INSTALLER_SCRIPT]
        for script, values in sets.items():
            with self.subTest(script=script):
                expected = first if script == INSTALLER_SCRIPT else first - WAKE_IMPORTS
                self.assertEqual(values, expected, f"{script} excludes differ: {values ^ expected}")

    def test_wake_imports_are_available_only_in_the_app(self) -> None:
        self.assertTrue(WAKE_IMPORTS <= set(self.excludes(INSTALLER_SCRIPT)))
        self.assertFalse(WAKE_IMPORTS & set(self.spec_excludes()))


if __name__ == "__main__":
    unittest.main()
