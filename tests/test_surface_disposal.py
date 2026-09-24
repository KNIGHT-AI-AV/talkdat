"""X-175: a surface that opens the microphone must release it however it ends.

The 0.4.104 UI/UX audit reported this and an independent adversarial re-read
CONFIRMED all seven P0 findings against the current source, then found MORE than
the audit did: fourteen distinct microphone owners, eleven of which can outlive
the UI that started them.

The worst example, and the one these tests are shaped around, is Live Captions.
Its engine stop existed in exactly one place, the START/STOP label inside the
captions window, while the window had FIVE ways to close:

    1. the pill's Features toggle          (overlay.toggle_captions, destroy + return)
    2. the control-row X                   (_close_control -> window.destroy)
    3. the glass title bar's second X      (auto-fitted, the audit missed this one)
    4. Escape                              (bound for every utility window)
    5. the window manager's close button   (WM_DELETE_WINDOW)

Every one destroyed the surface and left the capture thread running, with no
visible owner and no route back to it. Reopening built a fresh
`{"listening": False}`, so the tablet read START over a live microphone and the
next click inverted the label against the real engine.

Two mechanisms fix the class rather than the instance, and both are pinned here:

* `<Destroy>` is the chokepoint every close path funnels through, so disposal
  hangs there instead of on each individual close control.
* Shell navigation keeps the outgoing pixels as a transition cover and retires
  that Toplevel later, so disposal must run before the crossfade rather than
  waiting for delayed native destruction. That is how the Settings level meter
  and Mic Doctor stop while the old page remains briefly visible.
"""

from __future__ import annotations

import ast
import contextlib
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"
APP = ROOT / "knight_flow" / "app.py"


def overlay_source() -> str:
    return OVERLAY.read_text(encoding="utf-8")


def function_source(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    raise AssertionError(f"{name} not found in {path.name}")


class DisposalRunsOnEveryEndingTests(unittest.TestCase):
    def test_the_destroy_chokepoint_disposes(self) -> None:
        """One binding covers all five close paths, so none can be forgotten."""
        source = function_source(OVERLAY, "_utility_window")
        forget = source[
            source.index("def forget(event: tk.Event | None = None) -> None:"):
        ]
        self.assertIn("_dispose_window_instance(window, names=(name,))", forget)
        self.assertLess(
            forget.index("_dispose_window_instance"), forget.index("utility_windows.pop"),
            "the window is forgotten before its disposers run, so they cannot find it",
        )

    def test_a_shell_page_transition_disposes_before_retirement(self) -> None:
        """The outgoing tree stays visible briefly, but owns no live feature."""
        source = function_source(OVERLAY, "_utility_window")
        self.assertIn("_dispose_window(stale_name)", source)
        self.assertIn("utility_windows.pop(stale_name", source)

    def test_one_failing_disposer_cannot_block_the_others(self) -> None:
        """These release microphones. One broken surface must not keep the rest open."""
        source = function_source(OVERLAY, "_dispose_window")
        self.assertIn("try:", source)
        self.assertIn("except Exception:", source)

    def test_disposers_are_cleared_when_they_run(self) -> None:
        """Otherwise a reopened surface inherits the previous instance's cleanup
        and stops a stream belonging to a window that no longer exists."""
        source = function_source(OVERLAY, "_dispose_window_instance")
        self.assertIn("callbacks.clear()", source)
        self.assertIn("if candidate is callbacks", source)


class EveryRegisteredDisposerIsCallableWithNoArgumentsTests(unittest.TestCase):
    """The bug this file's author actually made, caught here rather than in the field.

    `_dispose_window` calls `dispose()` with no arguments. Registering a Tk
    handler such as `on_destroy(event)` therefore raises TypeError INSIDE the
    disposer's own except-and-log: the cleanup never runs, nothing crashes, and
    a log line is the only trace. That is precisely the silent-non-cleanup shape
    this change exists to remove, so it must not be reintroduced by the fix.
    """

    def _registered_disposers(self) -> list[tuple[str, str]]:
        text = overlay_source()
        tree = ast.parse(text)
        found: list[tuple[str, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "add_window_disposer"):
                continue
            if len(node.args) < 2:
                continue
            window = node.args[0]
            handler = node.args[1]
            name = window.value if isinstance(window, ast.Constant) else "?"
            if isinstance(handler, ast.Name):
                found.append((str(name), handler.id))
            elif isinstance(handler, ast.Lambda):
                found.append((str(name), "<lambda>"))
        return found

    def test_there_are_disposers_registered_at_all(self) -> None:
        self.assertGreaterEqual(
            len(self._registered_disposers()), 3,
            "the captions engine, the Settings meter and Mic Doctor should each register one",
        )

    def test_no_disposer_is_a_function_that_requires_arguments(self) -> None:
        text = overlay_source()
        tree = ast.parse(text)
        arities: dict[str, int] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                required = len(node.args.args) - len(node.args.defaults)
                arities[node.name] = max(0, required)

        offenders = []
        for window, handler in self._registered_disposers():
            if handler == "<lambda>":
                continue
            required = arities.get(handler)
            if required:
                offenders.append(f"{window} -> {handler} needs {required} argument(s)")
        self.assertEqual(
            offenders, [],
            "a disposer is called as dispose(); these would raise TypeError inside "
            f"the disposer's own except-and-log and silently never clean up: {offenders}",
        )


class TheCaptionsEngineStopsOnEveryCloseTests(unittest.TestCase):
    def test_captions_registers_a_disposer(self) -> None:
        source = overlay_source()
        self.assertIn('self.add_window_disposer("captions"', source)

    def test_the_disposer_only_stops_a_running_engine(self) -> None:
        """Explicit stop is safe when idle; the legacy toggle must remain gated."""
        source = textwrap.dedent(function_source(OVERLAY, "stop_captions_engine"))
        for explicit in (False, True):
            for listening in (False, True):
                with self.subTest(explicit=explicit, listening=listening):
                    stop, toggle, sink = Mock(), Mock(), Mock()
                    callbacks = {"captions_stream": toggle}
                    if explicit:
                        callbacks["captions_stop"] = stop
                    owner = SimpleNamespace(callbacks=callbacks, _caption_state_sink=sink)
                    state = {"listening": listening}
                    namespace = {"self": owner, "state": state, "stream_state": sink,
                                 "contextlib": contextlib}
                    exec(compile(source, str(OVERLAY), "exec"), namespace)
                    namespace["stop_captions_engine"]()
                    self.assertEqual(stop.call_count, int(explicit))
                    self.assertEqual(toggle.call_count, int(not explicit and listening))
                    self.assertFalse(state["listening"])
                    self.assertIsNone(owner._caption_state_sink)

    def test_a_failed_start_no_longer_repaints_as_listening(self) -> None:
        """The label used to flip unconditionally inside a suppressed exception,
        so a start that failed still showed STOP and the next click "stopped" a
        microphone that had never opened."""
        source = textwrap.dedent(function_source(OVERLAY, "toggle_listen"))
        owner = SimpleNamespace(callbacks={"captions_stream": Mock(side_effect=RuntimeError("failed"))},
                                set_state=Mock())
        state, paint = {"listening": False}, Mock()
        namespace = {"self": owner, "state": state, "paint_listening": paint, "log": Mock()}
        exec(compile(source, str(OVERLAY), "exec"), namespace)
        self.assertEqual(namespace["toggle_listen"](), "break")
        self.assertFalse(state["listening"])
        paint.assert_not_called()
        owner.set_state.assert_called_once()
        for answer in (False, True, False):
            owner.callbacks["captions_stream"] = Mock(return_value=answer)
            namespace["toggle_listen"]()
            self.assertIs(state["listening"], answer)


class TranslationSpeakCannotEscapeItsWindowTests(unittest.TestCase):
    """P0-2. Speak starts a REAL push-to-talk dictation and installs the global
    result sink. Teardown cleared the sink and left the capture running, so the
    transcript arrived with nowhere to go and fell through to ordinary delivery:
    the person closed a translation window and their speech pasted into whatever
    application happened to be focused."""

    def test_teardown_cancels_rather_than_stops(self) -> None:
        """`push_to_talk_stop` FINALISES the dictation. With the sink already
        cleared, finalising is exactly what delivers it to the wrong place.

        The docstring of the code under test names `push_to_talk_stop` in order
        to explain why it must NOT be used, so this checks executable lines
        only. A guard that trips on its own explanation gets deleted for being
        annoying, and takes the rule with it.
        """
        source = overlay_source()
        block = source[source.index("def dispose_speak() -> None:"):][:1800]
        body = block[block.index('"""', block.index('"""') + 3) + 3:]
        code = " ".join(
            line for line in body.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertIn('self.callbacks.get("cancel")', code)
        self.assertNotIn(
            "push_to_talk_stop", code,
            "teardown finalises the dictation instead of discarding it",
        )

    def test_the_capture_is_cancelled_before_the_sink_is_cleared(self) -> None:
        """Otherwise a result can land in the gap, with capture live and no sink."""
        source = overlay_source()
        block = source[source.index("def dispose_speak() -> None:"):][:1800]
        self.assertLess(
            block.index('self.callbacks.get("cancel")'),
            block.index("self.onboarding_test_sink is finish_spoken"),
            "the sink is released before the capture is cancelled",
        )

    def test_only_our_own_sink_is_taken_back(self) -> None:
        """Clearing somebody else's sink hands THEIR transcript to auto-paste,
        which is the same defect relocated."""
        source = overlay_source()
        block = source[source.index("def dispose_speak() -> None:"):][:1800]
        self.assertIn("self.onboarding_test_sink is finish_spoken", block)

    def test_it_runs_on_page_navigation_too(self) -> None:
        self.assertIn('self.add_window_disposer("translation", dispose_speak)', overlay_source())


class OnboardingCaptureCannotEscapeTheWizardTests(unittest.TestCase):
    """P0-6, the same defect as Translation's Speak, in the worst place for it.

    The setup test promises on screen that "the setup test is routed into this
    box instead of whichever app was previously focused". Leaving the page
    cleared the sink and left the capture RUNNING, so the transcript arrived with
    nowhere to go and fell through to ordinary auto-paste, into whatever
    application sat behind the wizard -- during first-run setup.

    The old teardown also gated its stop on `test_started_by_button`, so a
    capture begun with the REAL trigger (keyboard, mouse, controller) escaped
    even that.
    """

    def _source(self) -> str:
        return (ROOT / "knight_flow" / "ui" / "onboarding.py").read_text(encoding="utf-8")

    def _dispose_body(self) -> str:
        text = self._source()
        block = text[text.index("    def _dispose_test_capture(self) -> None:"):][:2600]
        body = block[block.index('"""', block.index('"""') + 3) + 3:]
        return " ".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))

    def test_teardown_cancels_rather_than_stops(self) -> None:
        """`push_to_talk_stop` FINALISES, which with the sink gone is what pastes it."""
        code = self._dispose_body()
        self.assertIn('"cancel"', code)
        self.assertNotIn(
            "push_to_talk_stop", code,
            "the wizard finalises the dictation instead of discarding it",
        )

    def test_the_capture_is_cancelled_before_the_sink_is_cleared(self) -> None:
        code = self._dispose_body()
        self.assertLess(
            code.index('"cancel"'), code.index("onboarding_test_sink = None"),
            "the sink is released before the capture is cancelled, leaving a gap",
        )

    def test_only_our_own_sink_is_reclaimed(self) -> None:
        code = self._dispose_body()
        self.assertIn("is not self.test_sink", code)
        self.assertNotIn(
            "is not self._receive_test_result", code,
            "a fresh bound-method object can never prove ownership of the installed sink",
        )

    def test_a_trigger_started_capture_is_no_longer_exempt(self) -> None:
        """The old stop only ran when a BUTTON started the test, so a capture
        started with the real trigger walked past it."""
        text = self._source()
        destroy = text[text.index("    def _on_destroy(self, event: tk.Event) -> None:"):][:900]
        self.assertNotIn(
            "if self.test_started_by_button and", destroy,
            "teardown is gated on the button again, so trigger-started captures escape",
        )
        self.assertIn("_stop_page_activity()", destroy)

    def test_page_navigation_disposes_too(self) -> None:
        """Leaving the page is the reported path, not just closing the window."""
        text = self._source()
        stop = text[text.index("    def _stop_page_activity(self)"):][:2200]
        self.assertIn("_dispose_test_capture()", stop)


class BrowsingSettingsDoesNotOpenTheMicrophoneTests(unittest.TestCase):
    """X-187, audit P1-13. Reading your options is not consent to be recorded.

    The Settings level meter started whenever the Dictation page became VISIBLE,
    so someone browsing their settings had the microphone opened on them with a
    level bar as the only notice. Choosing an input device still starts it --
    that IS the act that wants a meter -- and leaving still stops it.

    The meter is also a registry owner now, so Panic ends it and the diagnostics
    pane names it while it runs. It was one of the surfaces that made
    "Mic/Deepgram are active only when session_active is true" false.
    """

    def test_switching_pages_can_only_stop_the_meter(self) -> None:
        source = overlay_source()
        handler = source[source.index("def stop_meter_when_leaving("):][:600]
        self.assertIn("stop_live_meter()", handler)
        self.assertNotIn(
            "start_live_meter()", handler,
            "changing page can start the microphone again",
        )

    def test_the_tab_change_binding_uses_the_stop_only_handler(self) -> None:
        source = function_source(OVERLAY, "open_settings")
        self.assertIn('"<<NotebookTabChanged>>"', source)
        self.assertIn("stop_meter_when_leaving", source)
        self.assertNotIn(
            'notebook.bind("<<NotebookTabChanged>>", refresh_live_meter', source,
            "merely viewing the Dictation page opens the microphone again",
        )

    def test_choosing_a_device_still_starts_the_meter(self) -> None:
        """The fix must not remove the meter from the one place it is wanted."""
        source = overlay_source()
        self.assertIn("device_box.bind(", source)
        self.assertIn('"<<ComboboxSelected>>"', source)
        self.assertIn("stop_live_meter(restart=audio_tab_selected())", source)

    def test_the_meter_is_a_disclosed_microphone_owner(self) -> None:
        source = overlay_source()
        self.assertIn("registry.acquire(", source)
        self.assertIn("SETTINGS_METER", source)
        self.assertIn("registry.release(token)", source)
        self.assertIn("DEFERRED_MICROPHONE_RELEASE", source)

    def test_the_meter_registers_its_own_stopper(self) -> None:
        """Panic must be able to end it without knowing what Settings is."""
        source = overlay_source()
        block = source[source.index("registry.acquire("):][:400]
        self.assertIn("stop=stop_live_meter", block)

    def test_a_stream_allocated_before_start_failure_is_closed(self) -> None:
        source = function_source(OVERLAY, "open_settings")
        start = source.index("def open_driver()")
        end = source.index("threading.Thread(", start)
        driver = source[start:end]

        self.assertIn("stream = None", driver)
        self.assertIn("if stream is not None:", driver)
        self.assertIn("stream.stop()", driver)
        self.assertIn("stream.close()", driver)
        self.assertLess(driver.index("stream.stop()"), driver.index("self._post_ui("))
        self.assertLess(driver.index("stream.close()"), driver.index("self._post_ui("))


class PanicCoversEveryMicrophoneOwnerTests(unittest.TestCase):
    def test_panic_sweeps_the_registry_not_just_the_session(self) -> None:
        """It was `self.cancel()` and nothing else, which stops one owner of
        fourteen."""
        source = function_source(APP, "panic_stop")
        self.assertIn("registry = microphone_registry()", source)
        self.assertIn("registry.stop_all()", source)
        self.assertIn("self.cancel()", source, "panic must still end the dictation session")

    def test_panic_reports_a_surface_that_would_not_let_go(self) -> None:
        """A panic button that appears to work is worse than one that visibly fails."""
        source = function_source(APP, "panic_stop")
        self.assertIn("remaining", source)
        self.assertIn("set_state", source)

    def test_panic_does_not_call_an_async_driver_close_a_failure(self) -> None:
        source = function_source(APP, "panic_stop")
        self.assertIn('owner.phase == "closing"', source)
        self.assertIn("Panic Stop is closing a registered mic test.", source)
        self.assertIn(
            "Panic Stop completed for dictation and registered mic tests.",
            source,
        )
        self.assertNotIn("The microphone is off.", source)
        self.assertIn("still_open = registry.owners()", source)

    def test_the_status_pane_no_longer_makes_the_false_claim(self) -> None:
        """It said, verbatim: "Mic/Deepgram are active only when session_active
        is true." That is false whenever any other surface holds the microphone,
        and it is the exact sentence someone reads to find out if they are being
        listened to."""
        text = overlay_source()
        self.assertNotIn(
            '"Mic/Deepgram are active only when session_active is true."', text,
            "the false microphone claim is back in the diagnostics pane",
        )
        self.assertIn("microphone_registry().describe()", text)

    def test_the_status_snapshot_answers_for_all_owners(self) -> None:
        source = function_source(APP, "status_snapshot")
        self.assertIn("microphone_in_use", source)
        self.assertIn("microphone_owners", source)


if __name__ == "__main__":
    unittest.main()
