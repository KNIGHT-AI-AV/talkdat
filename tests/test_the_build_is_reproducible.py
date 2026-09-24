"""X-230: the signed binary was built from whatever PyPI served that minute.

requirements.txt is entirely ranges -- websockets>=14.0, numpy>=1.26 -- with no
upper bound on most and no pin on ANY transitive dependency. So two builds of
the same commit could contain different code, and a compromised or merely
broken upstream release would land inside a binary carrying Knight AI+AV's
Authenticode signature.

That signature is the strongest claim this project makes about a file: it says
Knight made this. It was being applied to a tree nobody could reproduce.

requirements.lock pins every package, direct and transitive, to an exact
version and a set of SHA-256 hashes, and the build installs with
--require-hashes so a substituted artifact fails the build instead of shipping.

Verified rather than assumed: the lock was installed into a clean virtualenv
with --require-hashes, and pip resolved all 51 packages and verified every
hash. A lock nobody has installed from is a guess.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
LOCK = ROOT / "requirements.lock"
BUILDS = (ROOT / "build-exe.ps1", ROOT / "build-custom-installer.ps1")


def direct_requirements() -> set[str]:
    names = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        found = re.match(r"^([A-Za-z0-9._-]+)", line)
        if found:
            names.add(found.group(1).lower().replace("_", "-"))
    return names


def locked_packages() -> dict[str, str]:
    packages = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        # No escapes in the character class: a heredoc collapsed the
        # backslash and produced an unterminated set that raised at import.
        head = line.strip().split(" ")[0].rstrip(chr(92)).strip()
        found = re.match("^([A-Za-z0-9._-]+)==([^ ]+)$", head)
        if found:
            packages[found.group(1).lower().replace("_", "-")] = found.group(2)
    return packages


class TheLockExistsAndIsRealTests(unittest.TestCase):
    def test_the_extractors_find_something(self) -> None:
        """A guard whose inputs are empty passes forever."""
        self.assertGreaterEqual(len(direct_requirements()), 10)
        self.assertGreaterEqual(len(locked_packages()), 40, "the lock is missing transitive deps")

    def test_every_direct_requirement_is_pinned(self) -> None:
        missing = sorted(direct_requirements() - set(locked_packages()))
        self.assertEqual(
            missing, [],
            "these are declared but not locked, so the build resolves them live: "
            f"{missing}. Run: uv pip compile requirements.txt --generate-hashes "
            "--output-file requirements.lock",
        )

    def test_every_locked_line_carries_hashes(self) -> None:
        """A pin without a hash stops version drift but not substitution."""
        text = LOCK.read_text(encoding="utf-8")
        pinned = len(re.findall(r"^[A-Za-z0-9._-]+==", text, re.M))
        hashed = len(re.findall(r"--hash=sha256:", text))
        self.assertGreater(pinned, 0)
        self.assertGreaterEqual(
            hashed, pinned,
            "some locked package has no hash, so pip cannot detect a swapped artifact",
        )

    def test_nothing_in_the_lock_is_a_range(self) -> None:
        text = LOCK.read_text(encoding="utf-8")
        loose = re.findall(r"^([A-Za-z0-9._-]+)(>=|<=|~=|>|<)", text, re.M)
        self.assertEqual(loose, [], f"the lock contains ranges, so it is not a lock: {loose}")


class TheBuildActuallyUsesItTests(unittest.TestCase):
    """A lock nothing installs from is decoration. This is the half that
    matters, and it is the half that is easiest to forget when regenerating."""

    def test_both_build_scripts_install_from_the_lock_with_hash_checking(self) -> None:
        for script in BUILDS:
            with self.subTest(script=script.name):
                text = script.read_text(encoding="utf-8")
                self.assertIn("--require-hashes", text, f"{script.name} does not verify hashes")
                self.assertIn("requirements.lock", text)

    def test_no_build_script_still_installs_the_ranges(self) -> None:
        for script in BUILDS:
            with self.subTest(script=script.name):
                text = script.read_text(encoding="utf-8")
                installs = re.findall(r"pip install[^\n]*requirements\.txt", text)
                self.assertEqual(
                    installs, [],
                    f"{script.name} still installs the unpinned ranges: {installs}",
                )


class TheLockStaysHonestTests(unittest.TestCase):
    def test_it_records_how_it_was_made(self) -> None:
        """Otherwise the next person regenerates it a different way and the
        hashes change for reasons nobody can explain."""
        head = LOCK.read_text(encoding="utf-8")[:400]
        self.assertIn("uv pip compile", head)
        self.assertIn("--generate-hashes", head)


if __name__ == "__main__":
    unittest.main()
