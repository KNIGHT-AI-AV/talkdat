"""X-548: saving the config must be atomic, and two threads must not do it at once.

The app fires two anonymous beacons from two daemon threads at startup
(`report_install` and `report_heartbeat` in `knight_flow/activation_metrics.py`),
and each stamps its own flag and calls `save(config)`. On a fresh install both
guards are unsatisfied, so both fire together: the live HTTP log for
api.talkdat.app shows the resulting pair of `POST /v1/activation` landing 2-11ms
apart, three times in 26 hours.

`save_config` read the file, merged, and finished with `Path.write_text`, which
TRUNCATES the destination and then writes. Two things follow:

  * a crash, a kill or a full disk between the truncate and the write leaves
    config.json empty or half-written -- every setting, every custom word and
    every snippet gone;
  * two threads doing that to the same path at the same time can interleave.

This is not a hypothetical class for this file. `save_config`'s own X-140
comment records that the founder's diagnostics flag "was wiped twice by exactly
this class". X-140 fixed the carry-forward; it did not make the write atomic.

Both tests below assert a positive control FIRST -- that the hook they rely on
actually fired. X-547 was a guard that went green over a file it no longer
measured, because a negative assertion passes trivially when the code it watched
has moved. A test that silently stops exercising the write would otherwise
report this bug as fixed for ever.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow.config import load_config, save_config


class SaveConfigIsAtomicTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_home = os.environ.get("TALK_DAT_HOME")

    def tearDown(self) -> None:
        if self._old_home is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._old_home

    def test_a_crash_mid_write_must_not_destroy_the_existing_config(self) -> None:
        """The destination must never be the file being written into."""
        attempted: list[Path] = []

        def crashing_write_text(self_path, data, *args, **kwargs):  # type: ignore[no-untyped-def]
            attempted.append(Path(self_path))
            # Exactly what the stdlib does, and the whole bug: truncate...
            with open(self_path, "w", encoding="utf-8") as handle:
                handle.write(data[: len(data) // 2])
            # ...and then the process dies before the remainder lands.
            raise OSError("simulated crash mid-write")

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            config_file = Path(tmp, "config.json")

            config = load_config(Path(tmp))
            config["dictionary"] = {"words": ["Mayowa", "Talk DAT"], "terms": []}
            save_config(config)

            # Positive control: the good save really landed, so a later failure
            # is the crash and not an empty starting point.
            before = json.loads(config_file.read_text(encoding="utf-8-sig"))
            self.assertEqual(before["dictionary"]["words"], ["Mayowa", "Talk DAT"])

            config["dictionary"]["words"].append("Knight")
            with patch.object(Path, "write_text", crashing_write_text):
                with self.assertRaises(OSError):
                    save_config(config)

            # Read inside the temporary directory's lifetime; the assertions
            # below outlive it.
            after_crash = config_file.read_text(encoding="utf-8-sig")
            leftovers = sorted(item.name for item in Path(tmp).iterdir())

        # Positive control: if the hook never fired, this test measured nothing.
        self.assertTrue(
            attempted,
            "the crash hook never fired -- save_config no longer writes through "
            "Path.write_text, so this test proves nothing. Re-point the hook.",
        )
        # The real assertion: the crash hit a temporary file, not the config.
        self.assertNotIn(
            config_file,
            attempted,
            "save_config wrote directly into config.json; a crash mid-write "
            "leaves the founder's settings truncated on disk.",
        )
        # And the config on disk is still the last good one, in full.
        survived = json.loads(after_crash)
        self.assertEqual(survived["dictionary"]["words"], ["Mayowa", "Talk DAT"])
        # A failed save must not leave a half-written temporary behind either.
        self.assertEqual(
            leftovers,
            ["config.json"],
            "a failed save left litter next to the config: " + ", ".join(leftovers),
        )

    def test_two_beacon_threads_cannot_write_the_config_at_the_same_time(self) -> None:
        """report_install and report_heartbeat both save on a fresh install."""
        real_write_text = Path.write_text
        inside: list[int] = []
        overlapped: list[int] = []
        writes: list[int] = []
        guard = threading.Lock()

        def slow_write_text(self_path, data, *args, **kwargs):  # type: ignore[no-untyped-def]
            with guard:
                writes.append(1)
                inside.append(1)
                if len(inside) > 1:
                    overlapped.append(1)
            # Wide enough that an unserialised second writer is certain to be
            # inside this window too -- no timing luck either way.
            time.sleep(0.05)
            try:
                return real_write_text(self_path, data, *args, **kwargs)
            finally:
                with guard:
                    inside.pop()

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["TALK_DAT_HOME"] = tmp
            config = load_config(Path(tmp))
            save_config(config)

            # The real shape: one shared config dict, two daemon threads, each
            # stamping its own flag -- as activation_metrics.py does.
            metrics = config.setdefault("metrics", {})
            start = threading.Barrier(2)

            def beacon(flag: str) -> None:
                start.wait()
                metrics[flag] = True
                save_config(config)

            with patch.object(Path, "write_text", slow_write_text):
                threads = [
                    threading.Thread(target=beacon, args=("install_acked",)),
                    threading.Thread(target=beacon, args=("last_heartbeat_at",)),
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=30)

            persisted = json.loads(Path(tmp, "config.json").read_text(encoding="utf-8-sig"))

        # Positive control: both saves really went through the hooked write.
        self.assertGreaterEqual(
            len(writes),
            2,
            "fewer than two writes were observed -- the hook is not on the path "
            "save_config uses, so this test proves nothing. Re-point the hook.",
        )
        self.assertFalse(
            overlapped,
            "two threads were inside the config write at the same time; the "
            "install ping and the heartbeat do exactly this on every fresh install.",
        )
        # Neither beacon's flag may be lost to the other's write.
        self.assertTrue(persisted["metrics"].get("install_acked"))
        self.assertTrue(persisted["metrics"].get("last_heartbeat_at"))


if __name__ == "__main__":
    unittest.main()
