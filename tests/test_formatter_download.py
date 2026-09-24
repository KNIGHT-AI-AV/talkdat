from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from knight_flow.llm import pull_local_formatter_model

OVERLAY = Path(__file__).resolve().parents[1] / "knight_flow" / "overlay.py"


def config(model="qwen3:1.7b", api_base="http://127.0.0.1:11434"):
    return {"transforms": {"llm": {"provider": "ollama", "model": model, "api_base": api_base}}}


def ndjson(*events):
    return io.BytesIO(b"".join(json.dumps(e).encode() + b"\n" for e in events))


class TheMissingFormatterModelCanNowBeDownloadedTests(unittest.TestCase):
    """Settings could say the model was missing and offer nothing to do about it.

    Every other state on that panel had an action -- an install link when the
    engine is absent, a start instruction when it is not running -- and the one
    state the app could actually fix by itself was a sentence and a dead end.
    The remedy was a terminal command nobody was given, for a 1.4 GB download.

    Through the engine's HTTP API rather than `ollama pull`, for three reasons:
    the engine must already be running for this state to exist, the API reports
    byte progress where the executable redraws a progress bar, and it does not
    depend on PATH -- which on Windows routinely lacks Ollama even when Ollama
    is installed and running.
    """

    def test_a_successful_pull_is_confirmed_against_the_engine_inventory(self) -> None:
        """Not against the stream ending. A stream can end for other reasons."""
        events = ndjson({"status": "pulling", "total": 100, "completed": 50},
                        {"status": "success"})
        with patch("urllib.request.urlopen", return_value=events), \
             patch("knight_flow.llm._ollama_models", return_value={"qwen3:1.7b"}):
            ok, message = pull_local_formatter_model(config())
        self.assertTrue(ok)
        self.assertIn("ready", message.lower())

    def test_a_stream_that_ends_without_the_model_is_not_success(self) -> None:
        with patch("urllib.request.urlopen", return_value=ndjson({"status": "success"})), \
             patch("knight_flow.llm._ollama_models", return_value=set()):
            ok, message = pull_local_formatter_model(config())
        self.assertFalse(ok)
        self.assertIn("still is not listed", message)

    def test_an_error_in_the_stream_is_surfaced_rather_than_swallowed(self) -> None:
        with patch("urllib.request.urlopen", return_value=ndjson({"error": "model not found"})):
            ok, message = pull_local_formatter_model(config())
        self.assertFalse(ok)
        self.assertIn("model not found", message)

    def test_progress_is_reported_so_a_gigabyte_does_not_look_frozen(self) -> None:
        seen = []
        events = ndjson({"status": "pulling", "total": 200, "completed": 50},
                        {"status": "pulling", "total": 200, "completed": 200},
                        {"status": "success"})
        with patch("urllib.request.urlopen", return_value=events), \
             patch("knight_flow.llm._ollama_models", return_value={"qwen3:1.7b"}):
            pull_local_formatter_model(config(), lambda stage, pct: seen.append(pct))
        self.assertIn(25, seen)
        self.assertIn(100, seen)

    def test_it_refuses_rather_than_pretending_for_a_remote_engine(self) -> None:
        """There is nothing on this machine to download into."""
        ok, message = pull_local_formatter_model(config(api_base="https://ollama.example.com"))
        self.assertFalse(ok)
        self.assertIn("remote engine", message)

    def test_a_network_failure_returns_rather_than_raising(self) -> None:
        """It is wired to a button. An exception here would reach a --windowed
        build with no stderr and look like the button doing nothing."""
        with patch("urllib.request.urlopen", side_effect=OSError("connection reset")):
            ok, message = pull_local_formatter_model(config())
        self.assertFalse(ok)
        self.assertIn("did not finish", message)

    def test_malformed_lines_in_the_stream_are_skipped(self) -> None:
        body = io.BytesIO(b'{"status":"pulling","total":10,"completed":5}\nnot json\n\n{"status":"success"}\n')
        with patch("urllib.request.urlopen", return_value=body), \
             patch("knight_flow.llm._ollama_models", return_value={"qwen3:1.7b"}):
            ok, _ = pull_local_formatter_model(config())
        self.assertTrue(ok)


class TheDownloadButtonOnlyAppearsWhereItCanWorkTests(unittest.TestCase):
    """A button that cannot work is worse than no button."""

    def source(self) -> str:
        return OVERLAY.read_text(encoding="utf-8")

    def test_it_is_shown_only_when_the_engine_is_running_and_the_model_is_not(self) -> None:
        body = self.source()
        block = body[body.index("def refresh_formatter_ready"):]
        block = block[:block.index("ttk.Label(")]
        self.assertIn('status.get("engine_running") and not status.get("model_installed")', block)
        self.assertIn("pack_forget()", block)

    def test_the_early_returns_also_hide_it(self) -> None:
        """Otherwise a button shown once stays after the state has changed."""
        body = self.source()
        block = body[body.index("def refresh_formatter_ready"):]
        block = block[:block.index("ttk.Label(")]
        before_first_return = block[:block.index("return")]
        self.assertIn("pack_forget()", before_first_return)

    def test_the_download_does_not_run_on_the_ui_thread(self) -> None:
        """A gigabyte on the Tk thread freezes the pill and every window."""
        body = self.source()
        block = body[body.index("def download_formatter_model"):]
        block = block[:block.index("formatter_pull_button = ttk.Button")]
        self.assertIn("threading.Thread", block)
        self.assertIn("daemon=True", block)

    def test_the_state_is_re_read_rather_than_assumed_after_downloading(self) -> None:
        body = self.source()
        block = body[body.index("def download_formatter_model"):]
        block = block[:block.index("formatter_pull_button = ttk.Button")]
        self.assertIn("refresh_formatter_ready()", block)


if __name__ == "__main__":
    unittest.main()
