"""The four increments that had no caller: T5 (glossary import), T6 (the model
bench), T9 (failed spans of a kept take) and T10 (the measured saving's data).
Each is wired to its workspace operation; the view that words them is not part
of this (its copy is not approved). Fakes only: no window, device, network,
model or sound.
"""
from __future__ import annotations

import math
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from knight_flow import editing_measure, model_bench
from knight_flow.app import TalkDatApp
from knight_flow.web_shell.recovery_workspace import RecoveryWorkspace
from knight_flow.web_shell.shell_models import ModelManager
from knight_flow.web_shell.stats_workspace import StatsWorkspace
from knight_flow.web_shell.words_workspace import WordsWorkspace
from tests.test_app_session_lifecycle import _app

RATE = 16000


class _Home(unittest.TestCase):
    def setUp(self) -> None:
        self._old = os.environ.get("TALK_DAT_HOME")
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["TALK_DAT_HOME"] = self._tmp.name

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("TALK_DAT_HOME", None)
        else:
            os.environ["TALK_DAT_HOME"] = self._old
        self._tmp.cleanup()


# ---------------------------------------------------------------- T10
class APracticeTaskIsRecorded(unittest.TestCase):
    def config(self, enabled=True) -> dict:
        return {"editing_measure": {"enabled": enabled, "tasks": []}}

    def test_only_once_the_person_turned_it_on(self) -> None:
        for config in ({}, {"editing_measure": {}}, self.config(enabled="yes"), self.config(enabled=False)):
            self.assertIsNone(editing_measure.record_task(config, "typing", 40, 60.0))
        config = self.config()
        self.assertEqual(editing_measure.record_task(config, "typing", 40, 60.0, 2),
                         {"mode": "typing", "words": 40, "seconds": 60.0, "corrections": 2})
        self.assertEqual(len(config["editing_measure"]["tasks"]), 1)

    def test_counts_and_times_only_and_only_sane_ones(self) -> None:
        config = self.config()
        for args in (("speaking", 40, 60.0, 0), ("typing", 0, 60.0, 0), ("typing", 40.5, 60.0, 0),
                     ("typing", 40, 0, 0), ("typing", 40, math.nan, 0), ("typing", 40, math.inf, 0),
                     ("typing", 40, 7200, 0), ("typing", 40, 60.0, -1), ("typing", 40, "60", 0), ("typing", True, 60, 0)):
            self.assertIsNone(editing_measure.record_task(config, *args), args)
        self.assertEqual(config["editing_measure"]["tasks"], [])
        task = editing_measure.record_task(config, "dictation", 40, 41.256)
        self.assertEqual(set(task), {"mode", "words", "seconds", "corrections"})
        self.assertEqual(task["seconds"], 41.26)

    def test_the_newest_tasks_are_kept(self) -> None:
        config = self.config()
        for index in range(editing_measure.MAX_TASKS + 5):
            editing_measure.record_task(config, "typing", 10 + index, 30.0)
        tasks = config["editing_measure"]["tasks"]
        self.assertEqual(len(tasks), editing_measure.MAX_TASKS)
        self.assertEqual(tasks[-1]["words"], 10 + editing_measure.MAX_TASKS + 4)
        self.assertEqual(tasks[0]["words"], 15)

    def test_the_stats_workspace_takes_one_task(self) -> None:
        seen = []
        workspace = StatsWorkspace({}, lambda finish: finish(), record=lambda *args: seen.append(args) or True)
        self.assertEqual(workspace.handle({"operation": "record_task", "mode": "typing", "words": 40,
                                           "seconds": 60.0, "corrections": 1}), {"recorded": True})
        self.assertEqual(seen, [("typing", 40, 60.0, 1)])
        for bad in ({"operation": "record_task", "mode": "typing", "words": 40, "seconds": 60.0},
                    {"operation": "record_task", "mode": "typing", "words": 40, "seconds": 60.0, "corrections": 0,
                     "text": "what I typed"}):
            with self.assertRaises(ValueError):
                workspace.handle(bad)
        with self.assertRaises(ValueError):
            StatsWorkspace({}, lambda finish: finish()).handle(
                {"operation": "record_task", "mode": "typing", "words": 40, "seconds": 60.0, "corrections": 0})


class TheMeasuredSavingReachesStats(_Home):
    def test_recorded_tasks_become_the_measured_row(self) -> None:
        from knight_flow.history import history_stats
        from knight_flow.web_shell.workspace_adapter import Workspaces

        saved = []
        app = SimpleNamespace(config={"editing_measure": {"enabled": True, "tasks": []}})
        workspaces = Workspaces(app, saved.append, lambda: False)
        self.assertIsNone(history_stats(app.config)["minutes_saved_measured"])
        for mode, seconds in (("typing", 60.0),) * 3 + (("dictation", 40.0),) * 3:
            self.assertTrue(workspaces.record_editing_task(mode, 40, seconds, 0))
        self.assertEqual(len(saved), 6)
        measured = history_stats(app.config)["minutes_saved_measured"]
        self.assertEqual(measured["tasks"], 6)
        self.assertAlmostEqual(measured["median_change"], -0.333, places=3)
        app.config["editing_measure"]["enabled"] = False
        self.assertFalse(workspaces.record_editing_task("typing", 40, 60.0, 0))
        self.assertEqual(len(saved), 6, "a refused task is never saved")


# ---------------------------------------------------------------- T6
class TheBenchWaitsForQuiet(unittest.TestCase):
    def test_audio_apps_and_an_unreadable_list_hold_it(self) -> None:
        self.assertTrue(model_bench.audio_work_active(None))
        self.assertTrue(model_bench.audio_work_active(["explorer.exe", "Ableton Live 12 Suite.exe"]))
        self.assertTrue(model_bench.audio_work_active(["Resolve.exe"]))
        self.assertFalse(model_bench.audio_work_active(["explorer.exe", "notepad.exe", "Talk Dat!.exe"]))
        self.assertFalse(model_bench.audio_work_active([]))

    def test_the_gate_speaks_in_codes(self) -> None:
        self.assertEqual(model_bench.bench_gate(take_active=True, process_names=[]), "take_active")
        self.assertEqual(model_bench.bench_gate(take_active=False, process_names=None), "audio_work_active")
        self.assertEqual(model_bench.bench_gate(take_active=False, process_names=["explorer.exe"]), "")

    def test_the_runner_summarises(self) -> None:
        def transcribe(*, model_id, **_kwargs):
            if model_id == "broken":
                raise RuntimeError("no weights")
            return model_bench.PASSAGE if model_id == "good" else "please send the report"

        summary = model_bench.run_bench(["good", "rough", "broken"], render=lambda: (b"\x00\x01" * 8000, RATE, 1),
                                        transcribe=transcribe, memory=lambda: 256.0, warm_runs=1)
        self.assertEqual(summary["recommended"], "good")
        self.assertEqual(summary["failed"], ["broken"])
        broken = next(row for row in summary["results"] if row["model_id"] == "broken")
        self.assertIsNone(broken["warm_median_ms"], "an engine that never ran has no time, not infinity")
        self.assertEqual(next(row for row in summary["results"] if row["model_id"] == "good")["wer"], 0.0)


class _Model(SimpleNamespace):
    pass


class TheBenchFromLocalModels(unittest.TestCase):
    def manager(self, *, busy=False, names=("explorer.exe",), render_raises=False):
        self.folders = []

        def render(platform, folder):
            self.folders.append(folder)
            self.assertTrue(Path(folder).is_dir())
            if render_raises:
                raise RuntimeError("no voice")
            return b"\x00\x01" * 8000, RATE, 1

        tools = {"process_names": lambda: list(names) if names is not None else None, "render": render,
                 "transcribe": lambda *, model_id, **_k: (model_bench.PASSAGE if model_id == "good"
                                                          else "please send the report")}
        return ModelManager({}, lambda: busy, start_worker=lambda work: work(), bench_tools=tools)

    def installed(self, *ids):
        models = [_Model(id=model_id) for model_id in ids]
        return (patch("knight_flow.web_shell.shell_models.available_local_models", return_value=models),
                patch("knight_flow.web_shell.shell_models.is_downloaded", return_value=True))

    def test_refused_during_a_take_over_audio_work_or_with_nothing_installed(self) -> None:
        first, second = self.installed("good")
        with first, second:
            self.assertEqual(self.manager(busy=True).bench(), {"bench": {"state": "refused", "reason": "take_active"}})
            self.assertEqual(self.manager(names=["Ableton Live 12 Suite.exe"]).bench()["bench"]["reason"],
                             "audio_work_active")
            self.assertEqual(self.manager(names=None).bench()["bench"]["reason"], "audio_work_active")
        first, second = self.installed()
        with first, second:
            self.assertEqual(self.manager().bench()["bench"]["reason"], "no_installed_model")

    def test_a_run_reports_numbers_and_leaves_no_files(self) -> None:
        first, second = self.installed("good", "other")
        with first, second:
            manager = self.manager()
            self.assertEqual(manager.bench(), {"bench": {"state": "working"}})
        state = manager.bench_status()
        self.assertEqual(state["state"], "ready")
        self.assertEqual(state["result"]["recommended"], "good")
        self.assertEqual([row["model_id"] for row in state["result"]["results"]], ["good", "other"])
        self.assertTrue(self.folders and not Path(self.folders[0]).exists(), "the rendered passage is removed")

    def test_a_failed_run_is_an_error_state(self) -> None:
        first, second = self.installed("good")
        with first, second:
            manager = self.manager(render_raises=True)
            manager.bench()
        self.assertEqual(manager.bench_status(), {"state": "error"})
        self.assertFalse(Path(self.folders[0]).exists())

    def test_the_backend_starts_it_only_by_its_action(self) -> None:
        import inspect

        from knight_flow.web_shell import shell_backend

        source = inspect.getsource(shell_backend)
        self.assertIn("payload['name'] in ('model_bench', 'model_bench_status')", source)
        self.assertEqual(source.count("self.models.bench()"), 1)


# ---------------------------------------------------------------- T9
class AKeptTakesFailedParts(_Home):
    def capture(self, *, provider="local"):
        from knight_flow.audio_spool import start_safety_capture
        from tests.test_audio_spans import clipped, pcm, speech

        capture = start_safety_capture(mode="dictation", control="hold", provider=provider, model="")
        capture.append(pcm([speech(2.0, 1), clipped(1.0), speech(2.0, 2)]), RATE, 1, heard_voice=True)
        capture.finalize(status="interrupted")
        return capture.session_id

    def app(self, save_history=True):
        app = _app(object())
        app.config = {"privacy": {"save_history": save_history}}
        return app

    def wait(self) -> None:
        for thread in threading.enumerate():
            if thread.name == "TalkDatSpanAgain":
                thread.join(5.0)

    def test_the_spans_are_computed_once_and_kept(self) -> None:
        from knight_flow.audio_spool import safety_session

        session_id = self.capture()
        app = self.app()
        spans = TalkDatApp.take_spans(app, session_id)
        self.assertEqual([span["kind"] for span in spans], ["clipped"])
        self.assertEqual(safety_session(session_id)["audio_spans"]["spans"], spans)
        self.assertEqual(TalkDatApp.take_spans(app, "no-such-take"), [])

    def test_one_span_is_transcribed_again_beside_the_take(self) -> None:
        from knight_flow.audio_spool import read_safety_audio, safety_session

        session_id = self.capture()
        before_audio = read_safety_audio(session_id)
        before = dict(safety_session(session_id))
        heard = []

        def transcribe(config, pcm, rate, channels):
            heard.append((len(pcm), rate, channels, config.get("privacy", {}).get("local_only")))
            return "the words of that part"

        app = self.app()
        app.add_history = lambda entry: self.fail("a span retry never writes History")
        with patch("knight_flow.app.transcribe_pcm", transcribe):
            self.assertFalse(TalkDatApp.retranscribe_span(app, session_id, 5))
            self.assertTrue(TalkDatApp.retranscribe_span(app, session_id, 0))
            self.wait()
        span = TalkDatApp.take_spans(app, session_id)[0]
        expected_ms = span["end_ms"] - span["start_ms"] + 600
        self.assertAlmostEqual(heard[0][0] / (RATE * 2) * 1000, expected_ms, delta=5)
        self.assertTrue(heard[0][3], "a take that ran on this computer is transcribed on this computer again")
        after = safety_session(session_id)
        self.assertEqual(after["span_alternatives"]["0"]["text"], "the words of that part")
        self.assertEqual(read_safety_audio(session_id), before_audio, "the recording is unchanged")
        for key in ("final_text", "raw_transcript", "status"):
            self.assertEqual(after.get(key), before.get(key), key)

    def test_with_history_off_no_words_are_kept(self) -> None:
        from knight_flow.audio_spool import safety_session

        session_id = self.capture()
        app = self.app(save_history=False)
        with patch("knight_flow.app.transcribe_pcm", lambda *a: "private words"):
            self.assertTrue(TalkDatApp.retranscribe_span(app, session_id, 0))
            self.wait()
        self.assertNotIn("span_alternatives", safety_session(session_id))


class TheRecoveryWorkspaceShowsSpans(unittest.TestCase):
    ROW = {"session_id": "take-1", "has_audio": True, "span_alternatives": {"1": {"text": "again"}}}

    def workspace(self, rows=None, *, retry=lambda session_id, index: index < 2):
        self.retried = []

        def retranscribe(session_id, index):
            self.retried.append((session_id, index))
            return retry(session_id, index)

        spans = [{"kind": "clipped", "start_ms": 100, "end_ms": 900}, {"kind": "silent", "start_ms": 1000, "end_ms": 3000},
                 {"kind": "made-up", "start_ms": 1, "end_ms": 2}]
        return RecoveryWorkspace(lambda: rows if rows is not None else [self.ROW], None, None, None,
                                 spans=lambda session_id: spans, retranscribe=retranscribe)

    def identifier(self, row=None) -> str:
        return RecoveryWorkspace.identifier(row or self.ROW)

    def test_the_spans_of_one_take(self) -> None:
        result = self.workspace().handle({"operation": "spans", "id": self.identifier()})
        self.assertEqual(result, {"spans": [
            {"index": 0, "kind": "clipped", "start_ms": 100, "end_ms": 900, "alternative": ""},
            {"index": 1, "kind": "silent", "start_ms": 1000, "end_ms": 3000, "alternative": "again"}]})

    def test_one_span_again(self) -> None:
        workspace = self.workspace()
        self.assertEqual(workspace.handle({"operation": "retranscribe", "id": self.identifier(), "span": 1}),
                         {"requested": True, "span": 1})
        self.assertEqual(self.retried, [("take-1", 1)])
        with self.assertRaises(ValueError):
            workspace.handle({"operation": "retranscribe", "id": self.identifier(), "span": 7})
        for bad in ({"operation": "retranscribe", "id": self.identifier(), "span": "1"},
                    {"operation": "retranscribe", "id": self.identifier()},
                    {"operation": "spans", "id": self.identifier(), "extra": 1}):
            with self.assertRaises(ValueError):
                workspace.handle(bad)

    def test_a_take_without_audio_or_gone(self) -> None:
        silent = {"session_id": "take-2", "has_audio": False}
        with self.assertRaisesRegex(ValueError, "no recorded audio"):
            self.workspace([silent]).handle({"operation": "spans", "id": self.identifier(silent)})
        with self.assertRaisesRegex(ValueError, "no longer available"):
            self.workspace([]).handle({"operation": "spans", "id": self.identifier()})
        with self.assertRaises(ValueError):
            RecoveryWorkspace(lambda: [self.ROW], None, None, None).handle({"operation": "spans", "id": self.identifier()})


# ---------------------------------------------------------------- T5
GLOSSARY = "Gaffer\nBest boy, best boi\nhttps://example.com\nGaffer\nKubernetes\n"


class AGlossaryFromAFile(unittest.TestCase):
    def workspace(self, config=None, picked=("terms.txt", GLOSSARY)):
        self.saved = []
        config = config if config is not None else {"dictionary": {"words": [], "terms": [{"text": "Kubernetes"}],
                                                                   "replacements": []}, "snippets": []}

        def utility(action, value):
            self.assertEqual((action, value), ("glossary", "file"))
            return None if picked is None else (picked[1], picked[0])

        return WordsWorkspace(config, self.saved.append, utility=utility)

    def test_a_preview_is_codes_and_nothing_is_kept_yet(self) -> None:
        workspace = self.workspace()
        result = workspace.handle({"operation": "glossary_preview", "source": "file"})
        rows = [(row["text"], row["status"], row["reason"]) for row in result["rows"]]
        # "Gaffer" is in the file twice: the first is new, the second a duplicate.
        self.assertEqual([row for row in rows if row[0] == "Gaffer"],
                         [("Gaffer", "new", ""), ("Gaffer", "duplicate", "duplicate")])
        self.assertIn(("https://example.com", "rejected", "link"), rows)
        self.assertIn(("Kubernetes", "known", "known"), rows)
        allowed = set(WordsWorkspace.GLOSSARY_REASONS.values()) | {"", "other"}
        self.assertTrue(all(row["reason"] in allowed for row in result["rows"]), "no wording reaches the view")
        self.assertEqual(self.saved, [])
        self.assertEqual(self.workspace(picked=None).handle({"operation": "glossary_preview", "source": "file"}),
                         {"cancelled": True})
        with self.assertRaises(ValueError):
            workspace.handle({"operation": "glossary_preview", "source": "medical"})

    def test_only_the_accepted_terms_are_imported_and_removal_is_exact(self) -> None:
        workspace = self.workspace()
        before = [dict(term) for term in workspace.config["dictionary"]["terms"]]
        token = workspace.handle({"operation": "glossary_preview", "source": "file"})["token"]
        result = workspace.handle({"operation": "glossary_apply", "token": token, "accepted": ["Gaffer"],
                                   "confirmed": True})
        self.assertEqual(result["imported"], 1)
        terms = workspace.config["dictionary"]["terms"]
        self.assertEqual([term["text"] for term in terms], ["Kubernetes", "Gaffer"])
        self.assertEqual(terms[1]["source"]["name"], "terms.txt")
        removed = workspace.handle({"operation": "glossary_remove", "source": result["source_id"],
                                    "revision": workspace.revision()})
        self.assertEqual(removed["removed"], 1)
        self.assertEqual(workspace.config["dictionary"]["terms"], before)
        self.assertEqual(len(self.saved), 2)

    def test_a_preview_must_be_confirmed_fresh_and_its_own(self) -> None:
        workspace = self.workspace()
        token = workspace.handle({"operation": "glossary_preview", "source": "file"})["token"]
        for payload in ({"operation": "glossary_apply", "token": token, "accepted": ["Gaffer"], "confirmed": False},
                        {"operation": "glossary_apply", "token": "other", "accepted": ["Gaffer"], "confirmed": True},
                        {"operation": "glossary_apply", "token": token, "accepted": "Gaffer", "confirmed": True}):
            with self.assertRaises(ValueError):
                workspace.handle(payload)
        token = workspace.handle({"operation": "glossary_preview", "source": "file"})["token"]
        workspace.pending_glossary = (*workspace.pending_glossary[:2], workspace.pending_glossary[2] - 301,
                                      *workspace.pending_glossary[3:])
        with self.assertRaises(ValueError):
            workspace.handle({"operation": "glossary_apply", "token": token, "accepted": ["Gaffer"], "confirmed": True})
        self.assertEqual(self.saved, [])
        with self.assertRaises(ValueError):
            workspace.handle({"operation": "glossary_remove", "source": "nope", "revision": workspace.revision()})

    def test_an_import_lands_in_the_active_project(self) -> None:
        from knight_flow.word_scopes import new_project

        config = {"dictionary": {"words": [], "terms": [], "replacements": []}, "snippets": []}
        project = new_project(config, "Film")
        config["dictionary"]["active_project"] = project["id"]
        workspace = self.workspace(config)
        token = workspace.handle({"operation": "glossary_preview", "source": "file"})["token"]
        workspace.handle({"operation": "glossary_apply", "token": token, "accepted": ["Gaffer"], "confirmed": True})
        film = next(p for p in workspace.config["dictionary"]["projects"] if p["id"] == "film")
        self.assertEqual([term["text"] for term in film["terms"]], ["Gaffer"])
        self.assertEqual(workspace.config["dictionary"]["terms"], [])

    def test_the_picker_reads_one_file(self) -> None:
        from knight_flow.web_shell.workspace_adapter import Workspaces

        app = SimpleNamespace(config={}, overlay=SimpleNamespace(root=None))
        workspaces = Workspaces(app, lambda candidate: None, lambda: False)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "film terms.csv"
            path.write_bytes(b"Gaffer\r\nBest boy\r\n")
            with patch("tkinter.filedialog.askopenfilename", return_value=str(path)) as ask:
                self.assertEqual(workspaces.words_utility("glossary", "file"), ("Gaffer\nBest boy\n", "film terms.csv"))
            self.assertEqual(ask.call_args.kwargs["title"], "Import vocabulary pack", "no new wording")
            with patch("tkinter.filedialog.askopenfilename", return_value=""):
                self.assertIsNone(workspaces.words_utility("glossary", "file"))
            broken = Path(folder) / "latin1.txt"
            broken.write_bytes(b"caf\xe9 au lait\n")
            from knight_flow.glossary_import import read_file
            with self.assertRaisesRegex(ValueError, "not plain text or CSV"):
                read_file(str(broken))


if __name__ == "__main__":
    unittest.main()
