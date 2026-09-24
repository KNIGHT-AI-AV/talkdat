from __future__ import annotations

import unittest

from knight_flow.mac_support import IS_MAC
from knight_flow.hotkeys import normalize_hotkeys, render_chord, tk_keysym_to_canonical


class CapturedKeysMustSpeakTheDispatchersLanguageTests(unittest.TestCase):
    """A captured chord is only worth anything if it is spelled exactly the way
    the pynput dispatcher will spell the pressed keys at match time.

    Tk and pynput name keys differently -- Control_L vs ctrl, Prior vs page_up,
    Win_L vs cmd -- and the old typed interface papered over this by making the
    person guess the right spelling. Capture removes the guessing, which means
    the mapping has to be right instead.
    """

    def test_modifiers_map_to_the_dispatcher_names(self) -> None:
        shared = (
            ("Control_L", "ctrl"), ("Control_R", "ctrl"),
            ("Alt_L", "alt"),
            ("Shift_R", "shift"),
        )
        # Aqua reports Command as Meta_L and has no Windows key at all. Mapping
        # Meta_L to "alt" there stored Control+Command as "ctrl+alt": a chord
        # that renders correctly in the field, saves cleanly, and then only ever
        # fires on Control+Option.
        platform_specific = (
            (("Meta_L", "cmd"), ("Meta_R", "cmd"), ("Win_L", None), ("Super_R", None))
            if IS_MAC
            else (("Meta_L", "alt"), ("Win_L", "cmd"), ("Super_R", "cmd"))
        )
        for keysym, expected in shared + platform_specific:
            with self.subTest(keysym=keysym):
                self.assertEqual(tk_keysym_to_canonical(keysym), expected)

    def test_named_keys_map_to_the_dispatcher_names(self) -> None:
        for keysym, expected in (
            ("space", "space"), ("Return", "enter"), ("Tab", "tab"),
            ("Prior", "page_up"), ("Next", "page_down"),
            ("Home", "home"), ("End", "end"), ("Delete", "delete"),
        ):
            with self.subTest(keysym=keysym):
                self.assertEqual(tk_keysym_to_canonical(keysym), expected)

    def test_letters_digits_and_function_keys_pass_through(self) -> None:
        self.assertEqual(tk_keysym_to_canonical("A"), "a")
        self.assertEqual(tk_keysym_to_canonical("z"), "z")
        self.assertEqual(tk_keysym_to_canonical("7"), "7")
        self.assertEqual(tk_keysym_to_canonical("F5"), "f5")
        self.assertEqual(tk_keysym_to_canonical("F12"), "f12")

    def test_unknown_keys_are_refused_not_recorded(self) -> None:
        """Recording a name the dispatcher will never produce creates a chord
        that renders in the field but can never fire -- worse than ignoring the
        press, because the person watched themselves set it."""
        for keysym in ("KP_1", "Muhenkan", "XF86AudioMute", "Caps_Lock"):
            with self.subTest(keysym=keysym):
                self.assertIsNone(tk_keysym_to_canonical(keysym))

    def test_comma_is_deliberately_not_capturable(self) -> None:
        """The saved-text format separates alternate chords with a comma, so a
        captured comma would be reparsed as a chord break and silently drop the
        key from its own binding."""
        self.assertIsNone(tk_keysym_to_canonical("comma"))


class TheCapturedTextRoundTripsThroughTheSaveParserTests(unittest.TestCase):
    """Capture writes rendered text into the same field the save path parses.

    That is the whole design: no second persistence path, no new format. It
    only holds if parse(render(chord)) gives back the chord for everything
    capture can produce.
    """

    def _parse(self, raw: str) -> list[list[str]]:
        from knight_flow.overlay import Overlay

        return Overlay.__new__(Overlay)._parse_shortcuts(raw)

    def test_every_capturable_chord_survives_the_round_trip(self) -> None:
        for chord in (
            {"ctrl", "cmd"},
            {"ctrl", "cmd", "space"},
            {"shift", "alt", "z"},
            {"f5"},
            {"ctrl", "="},
            {"middle"},
            {"mouse4"},
        ):
            with self.subTest(chord=sorted(chord)):
                rendered = render_chord(chord)
                parsed = self._parse(rendered)
                self.assertEqual(len(parsed), 1, f"{rendered!r} parsed as multiple chords")
                normalized = normalize_hotkeys({"probe": parsed})["probe"][0]
                self.assertEqual(normalized, set(chord))


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(IS_MAC, "describes macOS keyboard naming")
class TheMacKeyboardIsSpelledCorrectlyTests(unittest.TestCase):
    """Everything a Mac user is shown or asked to press.

    Three separate places named the Windows key on a keyboard that has none: the
    keysym table used when rebinding, the onboarding keycaps, and the idle hint
    on the Pill. All three were reachable in the first two minutes of using the
    app.
    """

    def test_command_captures_as_cmd_not_alt(self) -> None:
        self.assertEqual(render_chord(["ctrl", tk_keysym_to_canonical("Meta_L")]), "ctrl+cmd")

    def test_option_is_still_alt(self) -> None:
        """Option must not also become cmd, or the two would be
        indistinguishable and Cmd+Alt chords could never be captured."""
        self.assertEqual(tk_keysym_to_canonical("Alt_L"), "alt")
        self.assertNotEqual(tk_keysym_to_canonical("Alt_L"), tk_keysym_to_canonical("Meta_L"))

    def test_onboarding_asks_for_keys_that_exist(self) -> None:
        from knight_flow.onboarding import hotkey_labels

        labels = hotkey_labels(("ctrl", "cmd"))
        self.assertNotIn("Win", labels)
        self.assertEqual(labels, ("Control", "Command"))

    def test_the_onboarding_rehearsal_can_recognise_command(self) -> None:
        """The Controls step waits for both keys before it will continue. With
        no Meta_L case it waited forever: the Ctrl keycap lit, the other stayed
        grey, and "now press the other key" never went away."""
        import inspect

        from knight_flow.ui import onboarding as ui_onboarding

        source = inspect.getsource(ui_onboarding.OnboardingWizard._event_key)
        self.assertIn("meta_l", source)

    def test_the_idle_hint_names_the_bound_chord(self) -> None:
        from knight_flow.config import DEFAULT_CONFIG
        from knight_flow.onboarding import chord_label

        hint = chord_label(DEFAULT_CONFIG, "hands_free", ("ctrl", "cmd", "space"))
        self.assertNotIn("Win", hint)
        # Ctrl+Cmd+Space is the macOS Character Viewer, so the default moved.
        self.assertEqual(hint, "Control+Command+D")


@unittest.skipUnless(IS_MAC, "the stuck-key watchdog on macOS")
class TheStuckKeyWatchdogNeedsARealAnswerTests(unittest.TestCase):
    """The watchdog exists to recover a hold whose key-release never arrived.

    Its only mechanism was GetAsyncKeyState, so on macOS it returned None and
    the watchdog fell back to trusting `self.pressed` -- the very event stream
    it exists to distrust. That is worse here than on Windows: Cocoa is known to
    withhold key-up events for other keys while Command is held, and Command is
    in the default push-to-talk chord, so the failure it guards against is the
    likely one rather than the exotic one.
    """

    def test_every_key_in_the_default_chords_can_be_polled(self) -> None:
        from knight_flow.config import DEFAULT_CONFIG
        from knight_flow.hotkeys import physical_key_down

        unpollable = []
        for action, chords in DEFAULT_CONFIG["hotkeys"].items():
            for chord in chords:
                for key in chord:
                    if physical_key_down(key) is None:
                        unpollable.append(f"{action}:{key}")
        self.assertEqual(
            unpollable, [],
            "these keys fall back to trusting the event stream the watchdog distrusts",
        )

    def test_it_answers_true_or_false_not_none_for_modifiers(self) -> None:
        from knight_flow.hotkeys import physical_key_down

        for key in ("cmd", "ctrl", "alt", "shift"):
            with self.subTest(key=key):
                self.assertIsInstance(physical_key_down(key), bool)

    def test_an_unknown_key_declines_to_answer(self) -> None:
        """None means "no opinion", and the caller then trusts its own record.
        Returning False instead would report every unmapped key as released and
        cancel holds that are still down."""
        from knight_flow.hotkeys import physical_key_down

        self.assertIsNone(physical_key_down("scroll_lock"))
