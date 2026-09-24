"""X-357: the counters must stop measuring us.

Read off the live service on 2026-08-23: 64 installs, 10 machines ever
active, 0 paying customers. A large share of those installs and actives were
the founder's own PC, the build Mac, and the release smoke test, which
installs and uninstalls the real product on every publish. Every one of them
sends the same anonymous beacon a customer sends, because the beacon is
anonymous by design and cannot tell the difference.

A metric that flatters you is worse than no metric: it is a decision made on
a lie. So one boolean now says "this is one of ours".

What this file defends:

  IT CANNOT CARRY IDENTITY. A boolean, decided locally, identical on every
  internal machine. Not a hostname, not a username, not a machine id. The
  beacon's privacy budget is the reason anyone should trust it, and a
  convenience field is exactly how such a budget gets widened.

  SILENCE MEANS CUSTOMER. Older clients send no flag at all, and every
  document written before the field existed has none. Those must keep
  counting as external, which is how they were already counted.

  A SOURCE CHECKOUT IS NEVER A CUSTOMER. Running unfrozen means a developer,
  so it is internal without anyone remembering to say so.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import unittest
from unittest import mock

from knight_flow import activation_metrics


class TheFlagCannotCarryIdentityTests(unittest.TestCase):
    def test_it_is_a_boolean_and_only_a_boolean(self) -> None:
        with mock.patch.object(sys, "frozen", True, create=True):
            with mock.patch.dict(os.environ, {"TALKDAT_INTERNAL": "1"}, clear=False):
                self.assertIs(activation_metrics.is_internal({}), True)

    def test_the_wire_payload_has_the_flag_and_an_exact_field_set(self) -> None:
        """The install ping's field list IS its privacy claim, so this reads
        the bytes that would actually leave the machine rather than trusting
        the source to still look right."""
        captured: list[dict] = []

        class Sent:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self): return b""

        def fake_urlopen(request, timeout=0):
            captured.append(json.loads(request.data.decode("utf-8")))
            return Sent()

        def run_now(target, name=None, daemon=None):
            thread = mock.Mock()
            thread.start = target
            return thread

        config = {"metrics": {"install_id": "a" * 32, "first_run_at": 1}}
        patches = (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.dict(os.environ, {"TALKDAT_INTERNAL": "1"}, clear=True),
            mock.patch.object(activation_metrics.threading, "Thread", side_effect=run_now),
            mock.patch.object(activation_metrics.urllib.request, "urlopen", fake_urlopen),
        )
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            activation_metrics.report_install(config, lambda _c: None, "https://example.test")

        self.assertEqual(len(captured), 1, "the install ping did not send")
        payload = captured[0]
        self.assertIs(payload["internal"], True)
        self.assertEqual(
            sorted(payload),
            ["firstRunAt", "installId", "internal", "platform", "stage", "version"],
            "the install ping's field set changed; justify the new field before widening it",
        )
        for value in payload.values():
            self.assertIsInstance(value, (str, int, bool))

    def test_a_source_checkout_is_internal_without_being_told(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            if hasattr(sys, "frozen"):
                del sys.frozen  # type: ignore[attr-defined]
            self.assertIs(activation_metrics.is_internal({}), True)


class SilenceMeansCustomerTests(unittest.TestCase):
    def test_a_packaged_build_with_no_marker_is_external(self) -> None:
        """The default must be "customer". An internal-by-accident default
        would quietly delete real adoption from the numbers, which is the
        same failure as counting ourselves, pointed the other way."""
        with mock.patch.object(sys, "frozen", True, create=True):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertIs(activation_metrics.is_internal({}), False)

    def test_the_config_marker_is_honoured(self) -> None:
        with mock.patch.object(sys, "frozen", True, create=True):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertIs(
                    activation_metrics.is_internal({"metrics": {"internal": True}}), True)

    def test_an_empty_environment_variable_does_not_mark_a_machine(self) -> None:
        with mock.patch.object(sys, "frozen", True, create=True):
            with mock.patch.dict(os.environ, {"TALKDAT_INTERNAL": ""}, clear=True):
                self.assertIs(activation_metrics.is_internal({}), False)
            with mock.patch.dict(os.environ, {"TALKDAT_INTERNAL": "0"}, clear=True):
                self.assertIs(activation_metrics.is_internal({}), False)


if __name__ == "__main__":
    unittest.main()
