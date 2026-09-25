"""X-338: local is fast, local is locked, auto is cloud-first, and the
ding lands with the words.

The founder's orders, one session: "when local is activated ... 100%
confirmed and guaranteed to not be uploading anything"; "we need to
speed this shit up ... on local only"; "auto is, by the way, always
cloud ... until cloud fails too many times", with a visible flag "right
above the pill ... permanently there while local's enabled"; and the
finish sound "should happen right as it pastes in".

X-531 reverses exactly one of those, on his later order: the permanent
flag is gone. It made sense while local was the exception cloud fell back
to; once X-480 deleted cloud it announced the person's own setting back at
them forever. Everything else here stands, the fence included -- the fence
was always the guarantee, and the flag was only ever a label on it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from knight_flow import net_fence
from knight_flow.net_fence import LocalOnlyBlocked, assert_cloud_allowed, set_local_only

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "knight_flow" / "app.py"
OVERLAY = ROOT / "knight_flow" / "overlay.py"
LOCAL_STT = ROOT / "knight_flow" / "local_stt.py"


def block(text: str, pattern: str) -> str:
    found = re.search(pattern, text, re.S)
    assert found, "anchor moved: " + pattern
    return found.group(0)


def code_only(source: str) -> str:
    """The same source with whole-line comments removed.

    A guard that asserts a broken shape is ABSENT has to read code, not prose.
    A comment that records what was removed will quote it -- that is the point
    of the comment -- and an absence check reading raw source fails on its own
    documentation. A check that does that gets deleted by the next person to
    hit it, so it reads code.
    """
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )


class TheFenceIsTheGuaranteeTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_local_only(False)

    def test_the_fence_blocks_cloud_and_admits_this_machine(self) -> None:
        set_local_only(True)
        with self.assertRaises(LocalOnlyBlocked):
            assert_cloud_allowed("https://api.example.com/v1/stt", "A test upload")
        assert_cloud_allowed("http://127.0.0.1:11434/api/chat", "Local Ollama")
        assert_cloud_allowed("http://localhost:8080/x", "Loopback")

    def test_the_fence_down_blocks_nothing(self) -> None:
        set_local_only(False)
        assert_cloud_allowed("https://api.example.com/v1/stt", "A test upload")

    def test_every_content_bearing_helper_checks_the_fence(self) -> None:
        """One check per outbound funnel. A new cloud helper that skips the
        fence re-opens the leak this file exists to close."""
        expectations = {
            "llm.py": 2,
            "translation.py": 1,
            "deepgram_live.py": 1,
        }
        for name, minimum in expectations.items():
            source = (ROOT / "knight_flow" / name).read_text(encoding="utf-8")
            self.assertGreaterEqual(
                source.count("assert_cloud_allowed("), minimum,
                f"{name} lost its fence check",
            )

    def test_the_route_switch_raises_and_lowers_the_fence(self) -> None:
        app = APP.read_text(encoding="utf-8")
        route = block(app, r"def set_route_mode\(self, mode: str\) -> bool:.*?self\.overlay\.set_state")
        self.assertIn('net_fence.set_local_only(mode == "local")', route)
        self.assertIn("warm_selected_local_model()", route,
                      "switching toward local must warm the engine NOW")


class LocalGotItsSpeedBackTests(unittest.TestCase):
    def test_the_thread_budget_rose_to_six(self) -> None:
        source = LOCAL_STT.read_text(encoding="utf-8")
        self.assertIn("return max(2, min(6, (os.cpu_count() or 4) // 2))", source)

    def test_dictation_no_longer_runs_below_normal(self) -> None:
        """X-107's cap stays; the priority sacrifice goes. A user-invoked
        dictation IS the foreground work."""
        source = LOCAL_STT.read_text(encoding="utf-8")
        transcribe = block(source, r"def transcribe\(\n.*?return _recognize_faster_whisper")
        self.assertNotIn("_yield_cpu_to_the_foreground()", transcribe)


class AutoIsCloudFirstTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = APP.read_text(encoding="utf-8")

    def test_three_misses_before_the_pc_takes_over(self) -> None:
        self.assertIn("self._cloud_failure_streak < 3", self.app)
        # 2026-09-23: the message was rewritten as two plain sentences (no
        # double dash); the promise it makes is the same.
        self.assertIn("After three misses, {platform_copy.THIS_COMPUTER} takes over", self.app)

    def test_the_switch_is_sticky_and_says_so_out_loud(self) -> None:
        """X-531: it used to also raise a permanent badge. The badge is gone;
        the sentence a person actually reads is the toast, which is what
        X-59.B asked for and what the outage test asserts end to end."""
        self.assertIn("self._auto_local_sticky = True", self.app)
        # X-743: said by the Pill itself, the fact as its title, the place as its detail.
        self.assertIn('"Your speech provider did not answer",', self.app)
        self.assertIn('detail=f"This dictation ran on {platform_copy.THIS_COMPUTER} instead.",', self.app)

    def test_stuck_flights_go_straight_local(self) -> None:
        sticky = block(self.app, r"_auto_local_sticky.*?sticky_model = local_fallback\.rescue_model")
        self.assertIn('provider_id != "local"', sticky)

    def test_recovery_unsticks_on_the_next_clean_dictation(self) -> None:
        """X-516: the background probe is gone, and success is the signal.

        The probe polled OUR /health every 120 seconds and, on a 200, unstuck
        the person. That was never sound: our service being up says nothing
        about whether the provider THEY use had recovered. Their own next
        clean dictation is the honest evidence, and it is what lowers the
        flag now.
        """
        self.assertNotIn("_start_cloud_recovery_probe", self.app)
        self.assertNotIn("TalkDatCloudRecovery", self.app)
        success = block(
            self.app,
            r"A clean remote dictation resets the failure streak.*?_auto_local_sticky = False",
        )
        self.assertIn("self._auto_local_sticky = False", success)


class TheDingLandsWithTheWordsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = APP.read_text(encoding="utf-8")

    def test_release_arms_and_delivery_plays(self) -> None:
        # One lazy wildcard only: chained ".*?\\n" under re.S backtracks
        # exponentially on a miss and hung this suite for three minutes.
        release = block(self.app, r"the finish sound was premature.*?self\._landing_sound_pending = True")
        self.assertIn("_landing_sound_pending = True", release)
        self.assertIn('if delivery.get("success"):\n            self.play_landing_sound()', self.app)

    def test_a_cancel_disarms_the_ding(self) -> None:
        cancel = block(self.app, r"self\._landing_sound_pending = False\n            self\.play_sound\(\"off\"\)\n            log\.info\(\"session cancelled\"\)")
        self.assertIn("_landing_sound_pending = False", cancel)

    def test_one_ding_per_dictation(self) -> None:
        helper = block(self.app, r"def play_landing_sound\(self\) -> None:.*?self\.play_sound\(\"off\"\)")
        self.assertIn("self._landing_sound_pending = False", helper)


class TheConstantBadgeIsRetiredTests(unittest.TestCase):
    """X-531. His call, on seeing it: "do we even need a constant shit??"

    X-338 raised a permanent "USING LOCAL MODEL" flag above the pill when local
    was the EXCEPTION -- what auto fell back to when cloud failed. X-480 deleted
    cloud. Of its three call sites the one it was built for was gated on
    route_mode == "auto", a mode that no longer exists, so it had been
    unreachable ever since; the two that still fired announced the person's own
    setting back at them on every launch, forever.

    Nothing about the guarantee changed. net_fence is still the guarantee, and
    the rescue still announces itself in words.
    """

    def test_no_surface_raises_a_permanent_local_badge(self) -> None:
        for path in (OVERLAY, APP):
            source = code_only(path.read_text(encoding="utf-8"))
            self.assertNotIn("set_local_flag", source, path.name)
            self.assertNotIn("USING LOCAL MODEL", source, path.name)

    def test_the_helpers_that_only_drew_it_went_with_it(self) -> None:
        """fit_box and centred_within were added the same night to make the
        badge render correctly at every display scale. Rendering a thing that
        should not exist is not a reason to keep dead helpers."""
        overlay = OVERLAY.read_text(encoding="utf-8")
        ui_scale_source = (ROOT / "knight_flow" / "ui_scale.py").read_text(encoding="utf-8")
        self.assertNotIn("centred_within", overlay)
        self.assertNotIn("def fit_box", ui_scale_source)

    def test_the_rescue_still_says_it_out_loud(self) -> None:
        """The promise that has to survive the badge."""
        app = APP.read_text(encoding="utf-8")
        self.assertIn('"Your speech provider did not answer",', app)
        self.assertIn('detail=f"This dictation ran on {platform_copy.THIS_COMPUTER} instead.",', app)
        self.assertIn("Transcribing on {platform_copy.THIS_COMPUTER} instead.", app)


if __name__ == "__main__":
    unittest.main()
