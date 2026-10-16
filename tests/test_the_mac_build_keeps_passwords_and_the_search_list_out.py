"""0.4.173 (g): build-mac.sh signs without writing the keychain search list and without a password in argv.

The default build signs the bundle with a self-signed local identity (the stable designated requirement that keeps the
owner's permissions across builds). Until 0.4.173 it put that keychain on the user's search list for the signing and
took it off again, and unlocked it with `security unlock-keychain -p "$pass"`, which shows the password to every user
in `ps`. Both break the Mac rules for agent runs (2026-10-15): the search list and the default keychain are never
written, and passwords reach `security` only on stdin, through its interactive mode. Every codesign already names the
keychain with --keychain, so the list was never needed (the Store path proved it: 8dcb47ea).
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

SCRIPT = (Path(__file__).resolve().parents[1] / "build-mac.sh").read_text(encoding="utf-8")


def logical_lines(text: str) -> list:
    """Lines with their backslash continuations joined, so an argument on the next line still counts."""
    lines, pending = [], ""
    for raw in text.splitlines():
        if raw.rstrip().endswith("\\"):
            pending += raw.rstrip()[:-1] + " "
            continue
        lines.append(pending + raw)
        pending = ""
    return lines


CODE = [line for line in logical_lines(SCRIPT) if line.strip() and not line.lstrip().startswith("#")]


def function(name: str) -> str:
    start = SCRIPT.index(f"{name}() {{")
    return SCRIPT[start:SCRIPT.index("\n}\n", start) + 3]


class TheBuildKeepsPasswordsAndTheSearchListOutTests(unittest.TestCase):
    def test_the_search_list_and_the_default_keychain_are_never_written(self) -> None:
        for line in CODE:
            self.assertFalse(re.search(r"\blist-keychains\b.*\s-s\b", line), line)
            self.assertNotIn("default-keychain", line)

    def test_no_password_reaches_argv(self) -> None:
        # A `security` command run directly (not `security -i` reading stdin) may carry no password variable.
        for line in CODE:
            direct = re.search(r"(^|[\s;&|(])security\s+(?!-i\b)", line)
            if direct and "sec_i" not in line:
                self.assertNotIn("$pass", line, line)

    def test_passwords_go_to_security_on_stdin(self) -> None:
        self.assertIn("sec_i() { printf '%s\\n' \"$1\" | security -i >/dev/null; }", SCRIPT)
        signing = function("sign_with_local_identity")
        self.assertIn('sec_i "unlock-keychain -p \\"$pass\\" \\"$LOCAL_KEYCHAIN\\""', signing)
        creating = function("ensure_local_identity")
        for command in ("create-keychain", "unlock-keychain", "set-key-partition-list"):
            self.assertRegex(creating, rf'sec_i "{command} ', f"{command} does not go through security -i")

    def test_every_signature_names_the_local_keychain(self) -> None:
        signing = function("sign_with_local_identity")
        calls = re.findall(r"codesign --force[^\n]*", signing)
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertIn('--keychain "$LOCAL_KEYCHAIN"', call)
        self.assertNotIn("list-keychains", signing)


if __name__ == "__main__":
    unittest.main()
