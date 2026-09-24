from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = (ROOT / "knight_flow" / "overlay.py").read_text(encoding="utf-8-sig")
APP = (ROOT / "knight_flow" / "app.py").read_text(encoding="utf-8-sig")

# Every name the overlay asks the app for, whether through the _callback helper
# or by reaching into the dict directly.
REQUESTED = re.compile(r'(?:_callback\(|callbacks\.get\()\s*"([a-z_]+)"')
# Registrations are a dict literal in app.py. The value is sometimes a bound
# method and sometimes a lambda, so match on the key alone.
REGISTERED = re.compile(r'"([a-z_]+)"\s*:\s*(?:self\.[a-z_]+|lambda\b)')
# Optional renderers register only after their host has initialized.
ASSIGNED = re.compile(r'callbacks\["([a-z_]+)"\]\s*=\s*self\.[a-z_.]+')


class UiCallbacksAreWiredTests(unittest.TestCase):
    """Every control the overlay exposes must reach a real handler.

    `Overlay._callback` falls back to `lambda: None` when a name is missing, so
    a renamed or mistyped callback produces a button that is fully drawn,
    fully clickable, and does nothing at all -- with no error anywhere. That is
    indistinguishable from a broken feature, and it is the same shape as the
    provider that was selectable in Settings while having no live adapter.
    """

    def test_every_callback_the_overlay_requests_is_registered(self) -> None:
        requested = set(REQUESTED.findall(OVERLAY))
        registered = set(REGISTERED.findall(APP)) | set(ASSIGNED.findall(APP))
        self.assertTrue(requested, "found no callback names in overlay.py; the regex has drifted")

        missing = sorted(requested - registered)
        self.assertEqual(
            missing,
            [],
            f"overlay controls with no handler in app.py (they would silently do nothing): {missing}",
        )

    def test_the_silent_fallback_is_still_the_thing_being_guarded(self) -> None:
        """If the fallback is ever removed, this guard can relax.

        Kept as a canary: the test above exists because a missing name fails
        silently rather than loudly. Should `_callback` start raising, that is a
        better fix than this test, and this assertion should fail to say so.
        """
        self.assertIn("self.callbacks.get(name, lambda: None)", OVERLAY)


if __name__ == "__main__":
    unittest.main()
