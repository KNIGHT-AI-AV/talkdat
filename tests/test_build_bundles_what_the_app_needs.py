from __future__ import annotations

import ast
import hashlib
import re
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The Windows spec is gitignored, so on a clean checkout it is absent and these
# tests error instead of guarding anything -- the failure they exist to catch
# could ship unnoticed. The macOS spec is committed for that reason, and each
# platform checks the spec it actually builds from.
SPEC = ROOT / ("TalkDat-mac.spec" if sys.platform == "darwin" else "Talk Dat!.spec")
ONBOARDING_ASSETS = (
    "01-arrival-stone.png",
    "02-access-continuity.png",
    "03-route-engine.png",
    "04-voice-instrument.png",
    "05-command-deck.png",
    "06-finish-engine.png",
)
ONBOARDING_ASSET_SHA256_FINGERPRINTS = {
    "01-arrival-stone.png": "07:62:ad:53:5f:cf:a8:10:95:47:ae:4a:60:07:96:03:38:0b:27:78:57:6f:50:38:93:2f:31:27:ce:48:59:c6",
    "02-access-continuity.png": "2b:30:90:db:b9:36:e3:5d:b7:4f:34:55:94:40:9d:42:fa:6c:18:bd:20:b8:c0:ea:72:6c:25:1b:a1:d7:6f:41",
    "03-route-engine.png": "81:8d:6f:58:b8:5e:6e:81:af:cf:6d:eb:8c:54:28:70:d4:da:71:04:d2:94:2d:6a:00:d1:6c:c4:29:23:c2:57",
    "04-voice-instrument.png": "37:98:45:3f:c4:cb:a8:01:d5:d5:0f:e6:52:24:1c:28:92:c1:f1:a3:25:bb:ba:d5:11:f7:d2:2f:4d:87:49:c0",
    "05-command-deck.png": "04:26:dd:7d:9c:cd:e7:64:c8:48:03:d1:64:17:5e:6f:64:1c:49:63:7e:d0:13:90:cc:0c:10:06:44:b5:8f:41",
    "06-finish-engine.png": "1d:b4:b7:b5:22:5e:d5:69:15:f1:66:3d:ef:9e:37:f9:55:23:9f:36:15:64:33:cb:3f:cd:45:ea:5c:d3:2e:4b",
}


def _sha256_fingerprint(payload: bytes) -> str:
    """Return the exact digest as a conventional colon-delimited fingerprint."""

    return ":".join(f"{byte:02x}" for byte in hashlib.sha256(payload).digest())


def _spec_onboarding_assets() -> tuple[str, ...]:
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "_ONBOARDING_ASSETS" for target in node.targets):
            value = ast.literal_eval(node.value)
            return tuple(str(name) for name in value)
    raise AssertionError(f"{SPEC.name} has no _ONBOARDING_ASSETS manifest")


def _build_script_onboarding_assets() -> tuple[str, ...]:
    script = (ROOT / "build-exe.ps1").read_text(encoding="utf-8-sig")
    match = re.search(r"\$RuntimeOnboardingAssets\s*=\s*@\((.*?)\)", script, re.DOTALL)
    if match is None:
        raise AssertionError("build-exe.ps1 has no RuntimeOnboardingAssets manifest")
    return tuple(re.findall(r'"([^"\r\n]+\.png)"', match.group(1)))


class TheBuildMustNotDropCryptographyTests(unittest.TestCase):
    """0.4.35 shipped a build that could not start at all.

        No module named 'cryptography.hazmat.bindings._rust'

    It died in `licensing.py` before a single line of our own code ran, because
    verifying the signed licence token needs cryptography, and cryptography's
    real work lives in a compiled extension reached through dynamic imports.
    PyInstaller's static analysis can miss exactly that, and when it does the
    build still reports success -- so the failure is invisible until somebody
    double-clicks the icon.

    Earlier builds worked by luck of the analysis rather than by instruction.
    This asserts the instruction is present, because the alternative is finding
    out from a customer whose app will not open.

    This does not replace launching the binary; nothing here proves the build
    ran. It proves the build was *told* to include the thing whose absence is
    fatal, which is the part that silently regressed.
    """

    def _spec(self) -> str:
        return SPEC.read_text(encoding="utf-8")

    def test_cryptography_is_collected_explicitly(self) -> None:
        self.assertIn(
            "collect_all('cryptography')", self._spec(),
            "cryptography is left to inference again; a build that drops it starts to "
            "nothing but a traceback dialog",
        )

    def test_the_compiled_binding_is_named_as_a_hidden_import(self) -> None:
        """The module the crash actually named. Naming it is belt and braces."""
        self.assertIn("cryptography.hazmat.bindings._rust", self._spec())

    def test_the_other_dependencies_with_native_extensions_stay_collected(self) -> None:
        """Same failure shape, same remedy. These have all needed it before."""
        for package in ("ctranslate2", "onnxruntime"):
            with self.subTest(package=package):
                self.assertIn(f"collect_all('{package}')", self._spec())

    def test_the_version_resource_is_generated_rather_than_reused(self) -> None:
        """A stale stamp is a quieter version of the same class of bug.

        Building straight from the spec used to reuse whatever the last release
        left in build/, so 0.4.35 reported 0.4.34 in its file properties -- the
        one number somebody checks to answer "am I running the new build?".
        """
        spec = self._spec()
        self.assertIn("_write_version_resource", spec)
        self.assertIn("version=_VERSION_RESOURCE", spec)


class TheLicenceCodeReallyDoesNeedCryptographyTests(unittest.TestCase):
    """Proves the dependency is real, so nobody removes the guard as redundant."""

    def test_licensing_imports_cryptography(self) -> None:
        source = (ROOT / "knight_flow" / "licensing.py").read_text(encoding="utf-8")
        self.assertIn("cryptography", source)

    def test_licensing_is_reached_during_a_cold_start(self) -> None:
        """It is not an optional path -- config imports it, and everything imports config.

        That is why the failure is total rather than a degraded feature: the
        import chain in the crash was app -> chimes -> config -> licensing ->
        cryptography, all at module load.
        """
        config = (ROOT / "knight_flow" / "config.py").read_text(encoding="utf-8")
        self.assertIn("from .licensing import", config)


class OnboardingArtworkMustShipTests(unittest.TestCase):
    """The redesigned first-run path must look the same outside the source tree.

    PyInstaller does not infer image files referenced at runtime. The app can
    therefore work perfectly in development while a customer receives blank
    artwork unless every image is named in the curated spec and survives into
    the onedir payload embedded by the installer.
    """

    def test_the_six_source_images_exist_and_are_png_files(self) -> None:
        asset_dir = ROOT / "knight_flow" / "assets" / "onboarding"
        actual = tuple(sorted(path.name for path in asset_dir.glob("*.png")))
        self.assertEqual(actual, ONBOARDING_ASSETS)
        for filename in ONBOARDING_ASSETS:
            with self.subTest(filename=filename):
                self.assertEqual(
                    (asset_dir / filename).read_bytes()[:8],
                    b"\x89PNG\r\n\x1a\n",
                    f"{filename} is named .png but has no PNG signature",
                )

    def test_the_reviewed_masters_keep_their_dimensions_and_bytes(self) -> None:
        """Catch accidental replacement, truncation, or silent re-export drift.

        PNG width and height are the first two unsigned integers in IHDR. This
        keeps the packaging gate independent of an optional image library.
        """

        asset_dir = ROOT / "knight_flow" / "assets" / "onboarding"
        observed_hashes: set[str] = set()
        for filename in ONBOARDING_ASSETS:
            with self.subTest(filename=filename):
                payload = (asset_dir / filename).read_bytes()
                self.assertGreaterEqual(len(payload), 24)
                self.assertEqual(payload[12:16], b"IHDR")
                self.assertEqual(struct.unpack(">II", payload[16:24]), (1200, 675))
                fingerprint = _sha256_fingerprint(payload)
                self.assertEqual(
                    fingerprint,
                    ONBOARDING_ASSET_SHA256_FINGERPRINTS[filename],
                )
                observed_hashes.add(fingerprint)
        self.assertEqual(len(observed_hashes), len(ONBOARDING_ASSETS))

    def test_the_source_integrity_receipt_matches_the_reviewed_masters(self) -> None:
        receipt = (
            ROOT / "knight_flow" / "assets" / "onboarding" / "README.md"
        ).read_text(encoding="utf-8")
        for filename, fingerprint in ONBOARDING_ASSET_SHA256_FINGERPRINTS.items():
            with self.subTest(filename=filename):
                self.assertIn(f"| `{filename}` | `{fingerprint}` |", receipt)

    def test_the_curated_spec_bundles_every_onboarding_image(self) -> None:
        spec = SPEC.read_text(encoding="utf-8")
        self.assertEqual(_spec_onboarding_assets(), ONBOARDING_ASSETS)
        self.assertIn(
            '(str(_ASSETS / "onboarding" / filename), "knight_flow/assets/onboarding")',
            spec,
        )
        self.assertIn("for filename in _ONBOARDING_ASSETS", spec)

    def test_the_windows_build_validates_source_and_packaged_images(self) -> None:
        script = (ROOT / "build-exe.ps1").read_text(encoding="utf-8-sig")
        self.assertEqual(_build_script_onboarding_assets(), ONBOARDING_ASSETS)
        self.assertIn('Assert-FilesExist -BasePath $OnboardingAssetsPath', script)
        self.assertIn('Assert-FilesExist -BasePath $PackagedOnboardingPath', script)
        self.assertIn('_internal\\knight_flow\\assets\\onboarding', script)
        self.assertIn('knight_flow\\assets\\onboarding', script)

    def test_the_installer_embeds_the_validated_onedir_payload(self) -> None:
        installer = (ROOT / "build-custom-installer.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('"--add-data", "$AppDir;payload/app"', installer)


class TheBundleMustShipTheThemeAndBrandAssetsTests(unittest.TestCase):
    """0.4.126's Mac dmg shipped without the theme materials, the brand font,
    the runtime icon set and the offline changelog. None of those is fatal --
    every loader falls back to flat colour, the system font, or nothing --
    which is exactly why the gap survived four Mac releases: the app merely
    looked plainer, and nothing said why. Each platform's spec must name them.
    """

    def _spec(self) -> str:
        return SPEC.read_text(encoding="utf-8")

    def test_the_theme_material_strips_are_bundled_by_glob(self) -> None:
        spec = self._spec()
        self.assertIn('"knight_flow/assets/materials"', spec)
        self.assertIn('(_ASSETS / "materials").glob("*.png")', spec)

    def test_the_brand_font_is_bundled(self) -> None:
        spec = self._spec()
        self.assertIn('"KnightDisplay.ttf"', spec)
        self.assertIn('"knight_flow/assets/fonts"', spec)

    def test_the_runtime_icon_set_is_bundled(self) -> None:
        self.assertIn('"knight_flow/assets/ui/icons/imagegen-v1/runtime"', self._spec())

    def test_the_offline_changelog_is_bundled(self) -> None:
        self.assertIn('(str(ROOT / "CHANGELOG.md"), ".")', self._spec())

    def test_the_source_assets_the_specs_name_exist(self) -> None:
        assets = ROOT / "knight_flow" / "assets"
        self.assertTrue((assets / "fonts" / "KnightDisplay.ttf").is_file())
        self.assertGreaterEqual(len(list((assets / "materials").glob("*.png"))), 50)
        runtime = assets / "ui" / "icons" / "imagegen-v1" / "runtime"
        self.assertGreaterEqual(len(list(runtime.glob("*.png"))), 30)


if __name__ == "__main__":
    unittest.main()
