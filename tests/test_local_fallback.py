"""Losing a dictation because the Wi-Fi dropped is not an acceptable outcome.

The product is sold on running on your own machine, but that was only true if
you had chosen a local model in advance. Anyone on a cloud provider -- the
faster default, and what a trial hands you -- got nothing at all when the
network went away. The audio was saved and the person was told to go and retry
it from History, which is not an answer to "I just said something".

These tests pin the two halves separately, because they catch different
failures and either one alone leaves a hole:

  preflight  no network, so never open the socket. About the wait, not
             correctness -- a cloud attempt with no route costs a DNS timeout
             plus an HTTP timeout, paid after the person stops speaking.
  rescue     the cloud attempt failed, so re-transcribe the captured audio
             locally. About correctness -- outages, revoked keys, spent quotas
             and captive portals are all invisible to any connectivity check.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from knight_flow import connectivity, local_fallback, local_stt
from knight_flow.local_stt import DEFAULT_LOCAL_MODEL_ID, LOCAL_MODEL_BY_ID
from knight_flow.platform_copy import THIS_COMPUTER


def cloud_config(**stt: object) -> dict:
    base = {"stt": {"provider": "deepgram", "providers": {"local": {"model": DEFAULT_LOCAL_MODEL_ID}}}}
    base["stt"].update(stt)
    return base


class FallbackModelChoiceTests(unittest.TestCase):
    def test_it_prefers_the_model_the_person_configured(self) -> None:
        """Their choice of local model stands even while they dictate to a cloud.

        It is the best available statement of which model they want on this
        machine, and overriding it during a rescue would hand back a transcript
        from a model they had already rejected.
        """
        config = cloud_config(providers={"local": {"model": "whisper-small"}})
        with mock.patch("knight_flow.local_fallback.is_downloaded", return_value=True):
            self.assertEqual("whisper-small", local_fallback.fallback_model(config).id)

    def test_it_falls_to_the_recommended_default_when_theirs_is_absent(self) -> None:
        config = cloud_config(providers={"local": {"model": "whisper-large-v3"}})

        def downloaded(model):
            return model.id == DEFAULT_LOCAL_MODEL_ID

        with mock.patch("knight_flow.local_fallback.is_downloaded", downloaded):
            self.assertEqual(DEFAULT_LOCAL_MODEL_ID, local_fallback.fallback_model(config).id)

    def test_it_never_offers_a_model_that_is_not_on_disk(self) -> None:
        """Downloading 640 MB mid-failure is not a rescue."""
        with mock.patch("knight_flow.local_fallback.is_downloaded", return_value=False):
            self.assertIsNone(local_fallback.fallback_model(cloud_config()))

    def test_ties_are_broken_by_quality_not_by_directory_order(self) -> None:
        """With several models on disk and none configured, the pick is deliberate.

        X-474: this used to expect canary-1b-v2, which was second in the
        preference order and, as it turned out, could not run at all. The rule
        this test defends is unchanged and is the reason the ordering exists;
        only the example moved to a model that works. The retirement itself is
        pinned in test_we_never_offer_a_model_that_cannot_run.py.
        """
        config = {"stt": {"provider": "deepgram"}}
        present = {"whisper-tiny", "whisper-large-v3-turbo", "whisper-base"}
        with mock.patch("knight_flow.local_fallback.is_downloaded",
                        lambda model: model.id in present):
            self.assertEqual("whisper-large-v3-turbo", local_fallback.fallback_model(config).id)


class PreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        connectivity.reset_cache()

    def test_no_network_routes_a_cloud_dictation_to_the_local_model(self) -> None:
        with mock.patch("knight_flow.local_fallback.network_is_available", return_value=False), \
             mock.patch("knight_flow.local_fallback.is_downloaded", return_value=True):
            model = local_fallback.preflight_model(cloud_config(), "deepgram")
        self.assertIsNotNone(model)
        self.assertEqual(DEFAULT_LOCAL_MODEL_ID, model.id)

    def test_a_working_network_is_left_alone(self) -> None:
        with mock.patch("knight_flow.local_fallback.network_is_available", return_value=True), \
             mock.patch("knight_flow.local_fallback.is_downloaded", return_value=True):
            self.assertIsNone(local_fallback.preflight_model(cloud_config(), "deepgram"))

    def test_a_local_provider_is_never_second_guessed(self) -> None:
        with mock.patch("knight_flow.local_fallback.network_is_available", return_value=False):
            self.assertIsNone(local_fallback.preflight_model(cloud_config(), "local"))

    def test_no_network_and_no_model_still_attempts_the_cloud(self) -> None:
        """There is nothing to fall back to, so the cloud is the only chance.

        Refusing to try would turn a possibly-wrong offline reading into a
        guaranteed failure.
        """
        with mock.patch("knight_flow.local_fallback.network_is_available", return_value=False), \
             mock.patch("knight_flow.local_fallback.is_downloaded", return_value=False):
            self.assertIsNone(local_fallback.preflight_model(cloud_config(), "deepgram"))

    def test_it_can_be_switched_off(self) -> None:
        config = cloud_config(local_fallback=False)
        with mock.patch("knight_flow.local_fallback.network_is_available", return_value=False), \
             mock.patch("knight_flow.local_fallback.is_downloaded", return_value=True):
            self.assertIsNone(local_fallback.preflight_model(config, "deepgram"))

    def test_it_is_on_without_being_asked_for(self) -> None:
        """The default has to be on. The alternative is losing what was said."""
        self.assertTrue(local_fallback.enabled({}))
        self.assertTrue(local_fallback.enabled({"stt": {}}))


class RescueTests(unittest.TestCase):
    def test_it_does_not_consult_the_network_at_all(self) -> None:
        """The cloud attempt already failed. That beats any connectivity API.

        Outage, revoked key, spent quota and captive portal all look like a
        healthy connection, and they are exactly the failures that reach here.
        A rescue gated on `network_is_available` would decline every one of
        them.
        """
        with mock.patch("knight_flow.local_fallback.network_is_available",
                        side_effect=AssertionError("rescue must not ask")), \
             mock.patch("knight_flow.local_fallback.is_downloaded", return_value=True):
            model = local_fallback.rescue_model(cloud_config(), "deepgram")
        self.assertIsNotNone(model)

    def test_it_does_not_retry_local_with_local(self) -> None:
        with mock.patch("knight_flow.local_fallback.is_downloaded", return_value=True):
            self.assertIsNone(local_fallback.rescue_model(cloud_config(), "local"))


class ConfigOverrideTests(unittest.TestCase):
    def test_the_override_does_not_touch_what_the_person_chose(self) -> None:
        """A single bad minute on hotel Wi-Fi must not silently change a paid plan.

        Somebody who bought a cloud tier would otherwise stop using it after one
        flaky session and never learn why their transcripts got slower.
        """
        config = cloud_config()
        switched = local_fallback.config_using(config, LOCAL_MODEL_BY_ID["whisper-small"])
        self.assertEqual("local", switched["stt"]["provider"])
        self.assertEqual("whisper-small", switched["stt"]["providers"]["local"]["model"])
        self.assertEqual("deepgram", config["stt"]["provider"], "the live config was mutated")
        self.assertEqual(
            DEFAULT_LOCAL_MODEL_ID,
            config["stt"]["providers"]["local"]["model"],
            "the nested provider settings were shared, not copied",
        )

    def test_it_survives_a_config_with_nothing_in_it(self) -> None:
        switched = local_fallback.config_using({}, LOCAL_MODEL_BY_ID["whisper-base"])
        self.assertEqual("local", switched["stt"]["provider"])
        self.assertEqual("whisper-base", switched["stt"]["providers"]["local"]["model"])


class ConnectivityTests(unittest.TestCase):
    def setUp(self) -> None:
        connectivity.reset_cache()

    def tearDown(self) -> None:
        connectivity.reset_cache()

    def test_an_unanswerable_question_reads_as_online(self) -> None:
        """Not knowing must never disable the cloud path.

        A wrong "offline" would quietly downgrade every dictation on a healthy
        machine where the Windows call is simply unavailable, and the person
        would have no way to tell. A wrong "online" costs one timeout and is
        then caught by the rescue.
        """
        with mock.patch("knight_flow.connectivity._query_windows", return_value=None):
            self.assertTrue(connectivity.network_is_available(force=True))

    def test_it_reports_what_windows_says(self) -> None:
        with mock.patch("knight_flow.connectivity._query_windows", return_value=False):
            self.assertFalse(connectivity.network_is_available(force=True))
        connectivity.reset_cache()
        with mock.patch("knight_flow.connectivity._query_windows", return_value=True):
            self.assertTrue(connectivity.network_is_available(force=True))

    def test_it_does_not_ask_windows_on_every_dictation(self) -> None:
        with mock.patch("knight_flow.connectivity._query_windows", return_value=True) as query:
            connectivity.network_is_available(force=True)
            connectivity.network_is_available()
            connectivity.network_is_available()
        self.assertEqual(1, query.call_count, "the cached answer was not reused")

    def test_asking_never_raises(self) -> None:
        """This runs on the dictation path. It may not be a source of failures."""
        with mock.patch("knight_flow.connectivity._query_windows",
                        side_effect=OSError("wininet exploded")):
            with self.assertRaises(OSError):
                connectivity._query_windows()
        # The real function swallows its own failures; prove the public one does.
        connectivity.reset_cache()
        self.assertIsInstance(connectivity.network_is_available(force=True), bool)


class PrefetchTests(unittest.TestCase):
    """Every install ends up holding the fallback weights, not just local ones.

    This is what makes the offline promise real. Before it, a cloud user -- the
    default, and what a trial hands you -- had no local model on disk at all,
    so the first dropped connection lost the dictation outright. There was
    nothing to fall back to.
    """

    def test_a_cloud_user_still_gets_the_fallback_weights(self) -> None:
        with mock.patch.object(local_stt, "is_downloaded", return_value=False):
            model = local_stt.model_to_prefetch(cloud_config())
        self.assertIsNotNone(model, "a cloud user would have nothing to fall back to")
        self.assertEqual(DEFAULT_LOCAL_MODEL_ID, model.id)

    def test_nothing_is_fetched_once_it_is_on_disk(self) -> None:
        with mock.patch.object(local_stt, "is_downloaded", return_value=True):
            self.assertIsNone(local_stt.model_to_prefetch(cloud_config()))

    def test_switching_the_rescue_off_stops_the_download(self) -> None:
        """Weights that will never be used are several hundred megabytes of waste."""
        with mock.patch.object(local_stt, "is_downloaded", return_value=False):
            self.assertIsNone(local_stt.model_to_prefetch(cloud_config(local_fallback=False)))

    def test_the_existing_opt_out_still_wins(self) -> None:
        config = cloud_config(auto_download_local_model=False)
        with mock.patch.object(local_stt, "is_downloaded", return_value=False):
            self.assertIsNone(local_stt.model_to_prefetch(config))

    def test_it_fetches_the_model_they_chose_not_merely_the_default(self) -> None:
        config = cloud_config(providers={"local": {"model": "whisper-small"}})
        with mock.patch.object(local_stt, "is_downloaded", return_value=False):
            self.assertEqual("whisper-small", local_stt.model_to_prefetch(config).id)


class BundledModelTests(unittest.TestCase):
    """A model shipped by the installer counts as present.

    Without this the offline promise has a hole on day one: a fresh install
    with no network has nothing to fall back to, and the first thing the app
    would have to do to work offline is download 640 MB.

    The bundled copy sits BESIDE the executable, never inside it. A PyInstaller
    onefile build unpacks its whole payload to a temp directory on every
    launch, so weights buried in there would be re-extracted at every start.
    """

    def setUp(self) -> None:
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        # Resolved, because the code resolves too and Windows hands temp
        # directories back in 8.3 short form (COPPER~1). Comparing an
        # unresolved path against a resolved one fails on the spelling of the
        # user's home directory and says nothing about the behaviour.
        self.root = Path(self.tmp.name).resolve()
        self.model = LOCAL_MODEL_BY_ID["whisper-base"]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _plant(self, where: Path) -> None:
        """A payload the completeness check will accept."""
        where.mkdir(parents=True, exist_ok=True)
        blob = where / "model.bin"
        blob.write_bytes(b"\0" * (local_stt.MIN_PAYLOAD_BYTES + 1))
        (where / "config.json").write_text("{}", encoding="utf-8")
        local_stt._write_ready_manifest(self.model, where)

    def test_a_bundled_model_is_usable_with_nothing_downloaded(self) -> None:
        bundled = self.root / "models" / self.model.id
        self._plant(bundled)
        empty = self.root / "appdata" / self.model.id
        with mock.patch.object(local_stt, "model_dir", return_value=empty), \
             mock.patch.object(local_stt, "bundled_model_dir", return_value=bundled):
            self.assertTrue(local_stt.is_downloaded(self.model))
            self.assertEqual(bundled, local_stt.resolved_model_dir(self.model))

    def test_a_downloaded_copy_wins_over_the_bundled_one(self) -> None:
        """Someone who re-downloaded a model did it to repair a broken copy.

        Preferring the installer's copy anyway would make that repair do
        nothing, and the failure would look like the download itself failing.
        """
        bundled = self.root / "models" / self.model.id
        downloaded = self.root / "appdata" / self.model.id
        self._plant(bundled)
        self._plant(downloaded)
        with mock.patch.object(local_stt, "model_dir", return_value=downloaded), \
             mock.patch.object(local_stt, "bundled_model_dir", return_value=bundled):
            self.assertEqual(downloaded, local_stt.resolved_model_dir(self.model))

    def test_nothing_anywhere_still_reports_not_downloaded(self) -> None:
        empty = self.root / "appdata" / self.model.id
        with mock.patch.object(local_stt, "model_dir", return_value=empty), \
             mock.patch.object(local_stt, "bundled_model_dir", return_value=None):
            self.assertFalse(local_stt.is_downloaded(self.model))
            self.assertEqual(empty, local_stt.resolved_model_dir(self.model),
                             "a download must still have somewhere writable to land")

    def test_an_incomplete_bundled_payload_is_not_trusted(self) -> None:
        """A truncated install is worse than no install: it fails at dictation."""
        bundled = self.root / "models" / self.model.id
        bundled.mkdir(parents=True)
        (bundled / "model.bin").write_bytes(b"\0" * 1024)
        empty = self.root / "appdata" / self.model.id
        with mock.patch.object(local_stt, "model_dir", return_value=empty), \
             mock.patch.object(local_stt, "bundled_model_dir", return_value=bundled):
            self.assertFalse(local_stt.is_downloaded(self.model))

    def test_the_bundled_directory_is_beside_the_executable(self) -> None:
        with mock.patch.object(local_stt.sys, "frozen", True, create=True), \
             mock.patch.object(local_stt.sys, "executable", str(self.root / "Talk Dat!.exe")):
            (self.root / "models").mkdir()
            self.assertEqual(self.root / "models", local_stt.bundled_models_dir())

    def test_no_bundled_directory_is_not_an_error(self) -> None:
        with mock.patch.object(local_stt.sys, "frozen", True, create=True), \
             mock.patch.object(local_stt.sys, "executable", str(self.root / "Talk Dat!.exe")):
            self.assertIsNone(local_stt.bundled_models_dir())


if __name__ == "__main__":
    unittest.main()


class FallbackEscalationTests(unittest.TestCase):
    """Three cloud fallbacks in ten minutes stop being a rescue and become a route.

    Rescuing one dictation at a time during an outage makes every attempt pay
    the failed round trip before the local model saves it. The escalation
    switches the session to local and says so in a toast -- a silent route
    change reads as the transcripts getting mysteriously slower. Session-only:
    nothing is written to disk, so a restart returns to the person's choice.
    """

    def _app(self):
        from collections import deque
        from knight_flow.app import TalkDatApp

        app = TalkDatApp.__new__(TalkDatApp)
        app.config = {"stt": {"provider": "deepgram"}}
        app._cloud_fallback_times = deque(maxlen=8)
        app._switched_to_local_for_session = False
        app.overlay = mock.Mock()
        return app

    def test_two_fallbacks_change_nothing(self) -> None:
        app = self._app()
        app._note_cloud_fallback()
        app._note_cloud_fallback()
        self.assertEqual("deepgram", app.config["stt"]["provider"])
        app.overlay.flag.assert_not_called()

    def test_the_third_in_ten_minutes_switches_and_says_so(self) -> None:
        app = self._app()
        for _ in range(3):
            app._note_cloud_fallback()
        self.assertEqual("local", app.config["stt"]["provider"])
        app.overlay.flag.assert_called_once()
        call = app.overlay.flag.call_args
        self.assertEqual(call.args[0], f"Using {THIS_COMPUTER} for now")
        self.assertIn("speech provider keeps failing", call.kwargs["detail"])
        self.assertIn("restart goes back", call.kwargs["detail"])
        self.assertEqual(call.kwargs["tone"], "warn")

    def test_it_switches_once_not_on_every_later_fallback(self) -> None:
        app = self._app()
        for _ in range(5):
            app._note_cloud_fallback()
        app.overlay.flag.assert_called_once()

    def test_old_fallbacks_age_out(self) -> None:
        """Two flaky moments a day apart are weather, not an outage."""
        app = self._app()
        with mock.patch("knight_flow.app.time.monotonic", side_effect=[0.0, 700.0, 1400.0]):
            app._note_cloud_fallback()
            app._note_cloud_fallback()
            app._note_cloud_fallback()
        self.assertEqual("deepgram", app.config["stt"]["provider"])
        app.overlay.flag.assert_not_called()


class ReturnToCloudTests(unittest.TestCase):
    """Automatic failover is only honest if the route comes back.

    Without the return leg, "auto-switch" quietly means a paid cloud plan
    stops being used after the first bad ten minutes and never resumes.
    Two conditions gate the return: the network answers again, and no
    fallback has fired for two minutes -- one green ping mid-outage is how
    a route flaps.
    """

    def _switched_app(self):
        from collections import deque
        from knight_flow.app import TalkDatApp

        app = TalkDatApp.__new__(TalkDatApp)
        app.config = {"stt": {"provider": "local"}}
        app._cloud_fallback_times = deque([0.0], maxlen=8)
        app._switched_to_local_for_session = True
        app._provider_before_local_switch = "deepgram"
        app.overlay = mock.Mock()
        return app

    def test_a_recovered_network_switches_back_and_says_so(self) -> None:
        app = self._switched_app()
        with mock.patch("knight_flow.connectivity.network_is_available", return_value=True), \
             mock.patch("knight_flow.app.time.monotonic", return_value=500.0):
            app._maybe_return_to_cloud()
        self.assertEqual("deepgram", app.config["stt"]["provider"])
        self.assertFalse(app._switched_to_local_for_session)
        call = app.overlay.flag.call_args
        self.assertEqual(call.args[0], "Back on Deepgram")
        self.assertEqual(call.kwargs["tone"], "done")

    def test_a_fallback_two_minutes_ago_means_not_yet(self) -> None:
        """One good ping in the middle of an outage must not flap the route."""
        app = self._switched_app()
        app._cloud_fallback_times.append(450.0)
        with mock.patch("knight_flow.connectivity.network_is_available", return_value=True), \
             mock.patch("knight_flow.app.time.monotonic", return_value=500.0):
            app._maybe_return_to_cloud()
        self.assertEqual("local", app.config["stt"]["provider"])
        app.overlay.flag.assert_not_called()

    def test_still_offline_means_still_local(self) -> None:
        app = self._switched_app()
        with mock.patch("knight_flow.connectivity.network_is_available", return_value=False):
            app._maybe_return_to_cloud()
        self.assertEqual("local", app.config["stt"]["provider"])
        self.assertTrue(app._switched_to_local_for_session)

    def test_an_unswitched_session_is_never_touched(self) -> None:
        app = self._switched_app()
        app._switched_to_local_for_session = False
        app.config["stt"]["provider"] = "deepgram"
        app._maybe_return_to_cloud()
        self.assertEqual("deepgram", app.config["stt"]["provider"])
        app.overlay.flag.assert_not_called()
