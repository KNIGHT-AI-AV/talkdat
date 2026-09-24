"""X-605: every request to a local Ollama goes to 127.0.0.1, never "localhost".

Measured on the owner's PC 2026-09-23: Ollama listened on 127.0.0.1 only and
Python resolves "localhost" to ::1 first. On Windows each refused IPv6 connect
cost over a second before IPv4 was tried, so a 0.2-0.6 s formatting answer took
2.3-3.3 s, and the 0.35 s readiness check could give up before Ollama answered.
Saved settings still say "localhost"; the request layer rewrites it.
"""
from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from knight_flow.net_fence import loopback_ipv4


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TheLoopbackRewriteTests(unittest.TestCase):
    def test_localhost_becomes_ipv4_and_nothing_else_moves(self):
        self.assertEqual(loopback_ipv4("http://localhost:11434/api/chat"), "http://127.0.0.1:11434/api/chat")
        self.assertEqual(loopback_ipv4("http://LOCALHOST:11434"), "http://127.0.0.1:11434")
        self.assertEqual(loopback_ipv4("http://localhost/api/tags?x=1"), "http://127.0.0.1/api/tags?x=1")

    def test_other_hosts_are_left_alone(self):
        for url in ("http://127.0.0.1:11434/api/chat", "http://[::1]:11434/api/chat",
                    "http://192.168.1.20:11434/api/chat", "https://api.talkdat.app/v1",
                    "http://localhost.example.com:11434", "http://user:pw@localhost:11434", "not a url"):
            with self.subTest(url=url):
                self.assertEqual(loopback_ipv4(url), url)


class EveryOllamaRequestUsesIPv4Tests(unittest.TestCase):
    def capture(self, call, answer: dict) -> list[str]:
        seen: list[str] = []

        def fake_urlopen(request, timeout=None):
            seen.append(request.full_url)
            return _Response(json.dumps(answer).encode("utf-8"))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            call()
        return seen

    def test_the_formatter_request(self):
        from knight_flow import llm

        seen = self.capture(lambda: llm._post_json("http://localhost:11434/api/chat", {}, {}, 1.0), {})
        self.assertEqual(seen, ["http://127.0.0.1:11434/api/chat"])

    def test_the_model_list_and_the_loaded_list(self):
        from knight_flow import llm

        with patch.dict("os.environ", {llm.LOCAL_ENGINE_OFFLINE_ENV: ""}):
            seen = self.capture(lambda: llm._ollama_models("http://localhost:11434"), {"models": []})
        self.assertTrue(seen)
        self.assertTrue(all(url.startswith("http://127.0.0.1:11434/") for url in seen), seen)

    def test_no_request_site_builds_a_localhost_url_unrewritten(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "knight_flow"
        for name in ("llm.py", "translation.py", "text_pipeline.py"):
            source = (root / name).read_text(encoding="utf-8")
            for line in source.splitlines():
                if "urllib.request.Request(" in line and "/api/" in line:
                    with self.subTest(file=name, line=line.strip()):
                        self.assertIn("loopback_ipv4(", line)


if __name__ == "__main__":
    unittest.main()
