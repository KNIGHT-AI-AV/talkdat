"""Open source, 2026-09-23, the macOS half: the Mac build is an official build
only when it says so, and it ships its licences like the Windows one.

knight/main's 0.4.157 taught build-exe.ps1 to bake OFFICIAL/SOURCE into the app
and to generate THIRD_PARTY_LICENSES.txt; tests/test_official_build.py and
tests/test_third_party_licenses.py pin the Windows side. What this file pins on
the Mac side:

  THE FLAG IS BAKED AROUND PYINSTALLER and the generated module is removed
  again, even when the build fails; --notarize refuses a SOURCE build before
  building.

  THE GPL-ONLY HELPERS STAY OUT of TalkDat-mac.spec too.

  THE LICENCES SHIP: generated strictly from the bundle, written into
  Contents/Resources before anything signs it, and at the root of the dmg.

  THE MAC PYAV WHEEL IS UNDERSTOOD. It names its libraries the Unix way
  (av/.dylibs/libavcodec.62.28.102.dylib), which the Windows-shaped patterns
  missed entirely: the Mac bundle would have shipped FFmpeg, x264 and x265
  with no entry and no GPL text, and --strict would not have noticed.
"""

from __future__ import annotations

import json
import re
import runpy
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "build-mac.sh"
MAC_SPEC = ROOT / "TalkDat-mac.spec"
DMG_SETTINGS = ROOT / "packaging" / "dmg_settings.py"
HELPERS = ("mouseinfo", "pymsgbox", "pyscreeze", "pygetwindow", "pyrect")

# The native libraries of av-18.1.0-cp311-abi3-macosx_14_0_arm64.whl (the PyPI
# file whose sha256 begins b30a4e8d), the wheel the Mac's Python 3.13 .venv
# installs for requirements.txt's av==18.1.0. Read from the wheel file on
# 2026-09-23, not typed from memory.
MAC_PYAV_18_1_0 = (
    "libSvtAv1Enc.4.1.0.dylib", "libavcodec.62.28.102.dylib", "libavdevice.62.3.102.dylib",
    "libavfilter.11.14.102.dylib", "libavformat.62.12.102.dylib", "libavutil.60.26.102.dylib",
    "libdav1d.7.dylib", "libmp3lame.0.dylib", "libopencore-amrnb.0.dylib", "libopencore-amrwb.0.dylib",
    "libopus.0.dylib", "libsharpyuv.0.1.2.dylib", "libswresample.6.3.102.dylib",
    "libswscale.9.5.102.dylib", "libvpx.12.dylib", "libwebp.7.2.0.dylib", "libwebpmux.3.1.2.dylib",
    "libx264.165.dylib", "libx265.216.dylib",
)


def _load_collect_licenses():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import collect_licenses
    finally:
        sys.path.pop(0)
    return collect_licenses


COLLECT = _load_collect_licenses()


def script() -> str:
    return BUILD_SCRIPT.read_text(encoding="utf-8")


def mac_bundle_files(names=MAC_PYAV_18_1_0) -> list[str]:
    """The wheel's libraries where PyInstaller puts them in the .app."""
    return [f"Contents/Frameworks/av/.dylibs/{name}" for name in names]


class TheMacBuildBakesTheFlagTests(unittest.TestCase):
    def test_flags_are_written_before_pyinstaller_and_removed_after(self) -> None:
        text = script()
        pyinstaller = text.index('"$PYTHON" -m PyInstaller')
        written = text.index('"$PYTHON" "$BUILD_FLAGS_SCRIPT"\n')
        self.assertLess(written, pyinstaller)
        self.assertIn('BUILD_FLAGS_SCRIPT="scripts/write_build_flags.py"', text)
        self.assertIn('"$PYTHON" "$BUILD_FLAGS_SCRIPT" --clean', text)
        after = text[pyinstaller:]
        self.assertLess(after.index("clean_build_flags"), after.index("==> Third-party licenses"))

    def test_a_failed_build_still_removes_the_generated_module(self) -> None:
        """set -e exits on a failed PyInstaller; only the EXIT trap still runs."""
        text = script()
        trap = text.index("trap clean_build_flags EXIT")
        self.assertLess(trap, text.index('"$PYTHON" "$BUILD_FLAGS_SCRIPT"\n'))
        self.assertLess(trap, text.index('"$PYTHON" -m PyInstaller'))

    def test_notarize_refuses_a_source_build_before_building(self) -> None:
        text = script()
        check = text.index('"$PYTHON" "$BUILD_FLAGS_SCRIPT" --require-official --not-before "$BUILD_STARTED"')
        self.assertLess(check, text.index('"$PYTHON" -m PyInstaller'))
        self.assertIn('if [ "$do_notarize" -eq 1 ]; then\n', text[check - 400:check])

    def test_the_login_check_and_the_venv_pin_survive(self) -> None:
        text = script()
        self.assertIn("stat -f '%Su' /dev/console", text)
        self.assertIn('"$_here/.venv/bin/python" -c "import PyInstaller"', text)

    def test_require_official_reads_the_receipt(self) -> None:
        from knight_flow.version import APP_VERSION
        from scripts import write_build_flags

        now = int(time.time())
        cases = (
            ({"official": True, "version": APP_VERSION, "written_at": now}, 0, 0),
            ({"official": False, "version": APP_VERSION, "written_at": now}, 0, 1),
            ({"official": True, "version": "0.0.1", "written_at": now}, 0, 1),
            ({"official": True, "version": APP_VERSION, "written_at": now - 600}, now - 60, 1),
            # a fork's own official build may bake its endpoints; only Knight's
            # release lane (build_mac_remote.py) refuses those
            ({"official": True, "version": APP_VERSION, "api_base": "https://a.example", "written_at": now}, 0, 0),
        )
        with tempfile.TemporaryDirectory() as temp:
            receipt = Path(temp) / "talk-dat-build-flags.json"
            with mock.patch.object(write_build_flags, "RECEIPT_PATH", receipt), \
                    mock.patch("builtins.print"):
                self.assertEqual(write_build_flags.main(["--require-official"]), 1, "no receipt at all")
                for payload, not_before, expected in cases:
                    receipt.write_text(json.dumps(payload), encoding="utf-8")
                    argv = ["--require-official"] + (["--not-before", str(not_before)] if not_before else [])
                    with self.subTest(payload=payload, not_before=not_before):
                        self.assertEqual(write_build_flags.main(argv), expected)


class TheMacSpecKeepsTheGplHelpersOutTests(unittest.TestCase):
    def test_the_same_five_as_the_windows_spec(self) -> None:
        excludes = COLLECT.spec_excludes(MAC_SPEC)
        for name in HELPERS:
            with self.subTest(module=name):
                self.assertIn(name, excludes, f"TalkDat-mac.spec would bundle {name}")
        windows = COLLECT.spec_excludes(ROOT / "Talk Dat!.spec")
        self.assertLessEqual(set(HELPERS), windows)

    def test_the_macos_backend_needs_none_of_them(self) -> None:
        """The exclusion is safe only while pyautogui's Mac backend imports none
        of the helpers; read the installed source rather than trust it."""
        try:
            import importlib.util

            spec = importlib.util.find_spec("pyautogui")
        except (ImportError, ValueError):
            spec = None
        if spec is None or not spec.origin:
            self.skipTest("pyautogui is not installed here")
        backend = Path(spec.origin).with_name("_pyautogui_osx.py")
        if not backend.exists():
            self.skipTest("this pyautogui has no macOS backend file")
        text = backend.read_text(encoding="utf-8")
        for name in HELPERS:
            with self.subTest(module=name):
                self.assertNotRegex(text, re.compile(rf"^\s*(?:import|from)\s+{name}\b", re.M))


class TheMacBuildShipsTheLicencesTests(unittest.TestCase):
    def test_they_are_generated_strictly_from_the_bundle_after_pyinstaller(self) -> None:
        text = script()
        collect = text.index('"$PYTHON" scripts/collect_licenses.py')
        self.assertLess(text.index('"$PYTHON" -m PyInstaller'), collect)
        line = text[collect:text.index("\n", text.index("--strict", collect))]
        for needle in ('--bundle "$BUNDLE"', '--analysis "$ANALYSIS_TOC"', "--spec TalkDat-mac.spec",
                       '--output "$RESOURCES/THIRD_PARTY_LICENSES.txt"', "--strict"):
            with self.subTest(needle=needle):
                self.assertIn(needle, line)
        # PyInstaller's workpath is <--workpath>/<spec name>.
        self.assertIn('ANALYSIS_TOC="build-mac/work/TalkDat-mac/Analysis-00.toc"', text)
        self.assertIn("--workpath build-mac/work", text)
        self.assertIn('RESOURCES="$BUNDLE/Contents/Resources"', text)
        self.assertIn('cp LICENSE "$RESOURCES/LICENSE.txt"', text)
        self.assertIn('cp NOTICE "$RESOURCES/NOTICE.txt"', text)

    def test_they_are_inside_the_bundle_before_anything_signs_it(self) -> None:
        """codesign seals Contents/Resources; a file added afterwards breaks the
        Developer ID signature and notarization."""
        text = script()
        copied = text.index('cp NOTICE "$RESOURCES/NOTICE.txt"')
        for signer in ("\n    ensure_local_identity\n", 'echo "==> Signing with ${TALK_DAT_SIGN_IDENTITY}"',
                       'echo "==> Packaging $DMG"'):
            with self.subTest(signer=signer.strip()):
                self.assertLess(copied, text.index(signer))

    def test_the_dmg_root_carries_all_three(self) -> None:
        namespace = runpy.run_path(str(DMG_SETTINGS), init_globals={"defines": {"app": "dist-mac/Talk DAT!.app"}})
        files = [str(path).replace("\\", "/") for path in namespace["files"]]
        self.assertEqual(files[0], "dist-mac/Talk DAT!.app")
        for name in ("LICENSE.txt", "NOTICE.txt", "THIRD_PARTY_LICENSES.txt"):
            with self.subTest(name=name):
                self.assertIn(f"dist-mac/Talk DAT!.app/Contents/Resources/{name}", files)
                self.assertIn(name, namespace["icon_locations"])
        # X-148's window is unchanged: the two icons it was drawn around stay put.
        self.assertEqual(namespace["icon_locations"]["Talk DAT!.app"], (165, 240))
        self.assertEqual(namespace["icon_locations"]["Applications"], (495, 240))
        # ...and the fallback image without dmgbuild carries them too.
        self.assertIn('cp "$RESOURCES/LICENSE.txt" "$RESOURCES/NOTICE.txt" "$RESOURCES/THIRD_PARTY_LICENSES.txt" '
                      '"$STAGE/"', script())


class TheMacPyavWheelTests(unittest.TestCase):
    def test_ffmpeg_x264_and_x265_are_found_under_their_mac_names(self) -> None:
        components = COLLECT.native_components(mac_bundle_files(), None, {})
        ffmpeg = next((c for c in components if c.name.startswith("FFmpeg")), None)
        self.assertIsNotNone(ffmpeg, "the Mac bundle's FFmpeg went unlisted")
        self.assertIn("GPL-2.0-or-later libraries (x264, x265)", ffmpeg.license)
        for name in ("libavcodec.62.28.102.dylib", "libswresample.6.3.102.dylib",
                     "libx264.165.dylib", "libx265.216.dylib"):
            with self.subTest(library=name):
                self.assertIn(name, ffmpeg.note)
        for label in ("LAME", "dav1d", "SVT-AV1", "Opus", "opencore-amr", "libvpx", "libwebp"):
            with self.subTest(companion=label):
                self.assertIn(f"  {label} (", ffmpeg.note)
        owed = COLLECT.required_texts(components)
        for text in ("GPL-2.0.txt", "GPL-3.0.txt", "LGPL-3.0.txt", "LGPL-2.1.txt"):
            with self.subTest(owed=text):
                self.assertIn(text, owed)

    def test_every_library_in_the_mac_wheel_has_a_licence_row(self) -> None:
        self.assertEqual(COLLECT.unaccounted_pyav_libraries(mac_bundle_files()), [])
        wheel = [f"av/.dylibs/{name}" for name in MAC_PYAV_18_1_0]
        self.assertEqual(COLLECT.unaccounted_pyav_libraries(wheel), [])

    def test_the_installed_wheel_has_a_row_for_every_library(self) -> None:
        """Whichever platform runs this: the Windows wheel here, the Mac one on the Mac."""
        table = COLLECT.installed()
        if "av" not in table:
            self.skipTest("PyAV is not installed here")
        files = [str(entry) for entry in table["av"].files or []]
        self.assertTrue(any(COLLECT.PYAV_LIBRARY.search(f.replace("\\", "/")) for f in files))
        self.assertEqual(COLLECT.unaccounted_pyav_libraries(files), [])

    def test_an_unknown_library_fails_the_strict_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp) / "Talk DAT!.app"
            libraries = bundle / "Contents" / "Frameworks" / "av" / ".dylibs"
            libraries.mkdir(parents=True)
            for name in (*MAC_PYAV_18_1_0, "libgnutls.30.dylib"):
                (libraries / name).write_bytes(b"\xcf\xfa\xed\xfe")
            self.assertEqual(COLLECT.unaccounted_pyav_libraries(
                [str(p.relative_to(bundle)).replace("\\", "/") for p in bundle.rglob("*") if p.is_file()]),
                ["libgnutls.30.dylib"])
            messages: list[str] = []
            with mock.patch.object(COLLECT, "collect", return_value=([], [], [])), \
                    mock.patch.object(COLLECT, "required_texts", return_value={}), \
                    mock.patch("builtins.print", side_effect=lambda *a, **k: messages.append(" ".join(map(str, a)))):
                code = COLLECT.main(["--bundle", str(bundle), "--output", str(Path(temp) / "out.txt"), "--strict"])
        self.assertEqual(code, 1)
        self.assertIn("libgnutls.30.dylib", " ".join(messages))

    def test_the_mac_system_libraries_are_named_the_mac_way(self) -> None:
        names = {c.name for c in COLLECT.native_components(
            ["Contents/Frameworks/libssl.3.dylib", "Contents/Frameworks/libcrypto.3.dylib",
             "Contents/Frameworks/libtcl9.0.dylib", "Contents/Frameworks/libtcl9tk9.0.dylib"], None, {})}
        self.assertIn("OpenSSL 3", names)
        self.assertIn("Tcl/Tk", names)

    def test_pythons_licence_is_found_on_a_posix_layout_too(self) -> None:
        """Windows keeps LICENSE.txt at the install root; macOS keeps it in
        lib/python3.X, which is where sysconfig's stdlib path points."""
        with tempfile.TemporaryDirectory() as temp:
            stdlib = Path(temp) / "lib" / "python3.13"
            stdlib.mkdir(parents=True)
            (stdlib / "LICENSE.txt").write_text("PSF", encoding="utf-8")
            with mock.patch.object(COLLECT.sys, "base_prefix", temp), \
                    mock.patch("sysconfig.get_paths", return_value={"stdlib": str(stdlib)}):
                self.assertEqual(COLLECT.python_license_file(), stdlib / "LICENSE.txt")


if __name__ == "__main__":
    unittest.main()
