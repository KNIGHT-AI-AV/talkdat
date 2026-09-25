"""X-761 (IP audit, 2026-09-24): the ASIO builds of PortAudio stay out.

The 0.4.167 bundle carried _sounddevice_data/portaudio-binaries/
libportaudio{32bit,64bit,arm64}-asio.dll. They are PortAudio compiled with
Steinberg's ASIO SDK, which comes under Steinberg's own license agreement
(the portaudio-binaries README points to it), not PortAudio's MIT license.
sounddevice loads them only when SD_ENABLE_ASIO is set; Talk DAT! never sets
it. The spec filters them out and a strict license run on a built bundle
refuses them.
"""

from __future__ import annotations

import ast
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "Talk Dat!.spec"
SHIPPED = ["libportaudio32bit-asio.dll", "libportaudio64bit-asio.dll", "libportaudioarm64-asio.dll"]
NEEDED = ["libportaudio32bit.dll", "libportaudio64bit.dll", "libportaudioarm64.dll", "libportaudio.dylib"]


def _spec_pattern() -> str:
    for node in ast.parse(SPEC.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_ASIO_BUILD" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("Talk Dat!.spec has no _ASIO_BUILD filter")


class TheSpecLeavesThemOutTests(unittest.TestCase):
    def test_the_filter_drops_exactly_the_asio_builds(self) -> None:
        pattern = _spec_pattern()
        for name in SHIPPED:
            with self.subTest(name=name):
                self.assertRegex(f"_sounddevice_data/portaudio-binaries/{name}", pattern)
        for name in NEEDED:
            with self.subTest(name=name):
                self.assertNotRegex(f"_sounddevice_data/portaudio-binaries/{name}", pattern)

    def test_the_filter_runs_on_both_lists_before_the_archive(self) -> None:
        spec = SPEC.read_text(encoding="utf-8")
        for line in ("a.binaries = [entry for entry in a.binaries if not _re.search(_ASIO_BUILD, entry[0])]",
                     "a.datas = [entry for entry in a.datas if not _re.search(_ASIO_BUILD, entry[0])]"):
            with self.subTest(line=line):
                self.assertIn(line, spec)
                self.assertLess(spec.index(line), spec.index("pyz = PYZ(a.pure)"))

    def test_the_app_never_asks_for_asio(self) -> None:
        for path in (ROOT / "knight_flow").rglob("*.py"):
            with self.subTest(file=path.name):
                self.assertNotIn("SD_ENABLE_ASIO", path.read_text(encoding="utf-8"))


class TheStrictRunRefusesThemTests(unittest.TestCase):
    def test_a_built_bundle_with_an_asio_build_is_named(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import collect_licenses
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "_internal" / "_sounddevice_data" / "portaudio-binaries"
            folder.mkdir(parents=True)
            (folder / "libportaudio64bit.dll").write_bytes(b"")
            self.assertEqual(collect_licenses.asio_builds(Path(temp)), [])
            (folder / "libportaudio64bit-asio.dll").write_bytes(b"")
            self.assertEqual(collect_licenses.asio_builds(Path(temp)), ["libportaudio64bit-asio.dll"])
        self.assertEqual(collect_licenses.asio_builds(None), [])


if __name__ == "__main__":
    unittest.main()
