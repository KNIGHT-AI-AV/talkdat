from __future__ import annotations

import json
import socket
import unittest
import urllib.error
import urllib.request

from knight_flow.http_api import ControlServer, host_is_loopback


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class HostHeaderTests(unittest.TestCase):
    def test_loopback_names_and_ports_are_accepted(self) -> None:
        for header in ("localhost", "localhost:4670", "127.0.0.1", "127.0.0.1:4670", "[::1]:4670", "LOCALHOST"):
            self.assertTrue(host_is_loopback(header), header)

    def test_rebound_and_missing_hostnames_are_rejected(self) -> None:
        # A page that resolves its own hostname to 127.0.0.1 still sends its own name.
        for header in ("evil.example:4670", "talkdat.example", "", "   ", "192.168.1.9:4670"):
            self.assertFalse(host_is_loopback(header), repr(header))


class ControlServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []
        self.server: ControlServer | None = None

    def tearDown(self) -> None:
        if self.server is not None:
            self.server.stop()

    def start(self, **remote: object) -> str:
        port = free_port()
        config = {"remote": {"enabled": True, "port": port, **remote}}
        callbacks = {
            "hands_free": lambda: self.calls.append("hands_free"),
            "panic": lambda: self.calls.append("panic"),
            "paste_last": lambda: self.calls.append("paste_last"),
            "status_provider": lambda: {"app": "running", "listening": False},
            "last_text": lambda: "the secret transcript",
        }
        self.server = ControlServer(config, callbacks)
        self.server.start()
        self.assertTrue(self.server.running, "control server did not start")
        return f"http://127.0.0.1:{port}"

    def get(
        self,
        url: str,
        host: str | None = None,
        token: str | None = None,
        sec_fetch_site: str | None = None,
    ) -> tuple[int, dict]:
        request = urllib.request.Request(url)
        if host is not None:
            request.add_header("Host", host)
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        if sec_fetch_site is not None:
            request.add_header("Sec-Fetch-Site", sec_fetch_site)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_disabled_remote_never_listens(self) -> None:
        server = ControlServer({"remote": {"enabled": False, "port": free_port()}}, {})
        server.start()
        self.addCleanup(server.stop)
        self.assertFalse(server.running)

    def test_status_and_actions_work_for_local_automation(self) -> None:
        base = self.start()
        code, body = self.get(f"{base}/status")
        self.assertEqual(code, 200)
        self.assertEqual(body["app"], "running")

        self.assertEqual(self.get(f"{base}/toggle")[0], 200)
        self.assertEqual(self.get(f"{base}/paste-last/")[0], 200)
        self.assertEqual(self.calls, ["hands_free", "paste_last"])

    def test_unknown_route_is_a_clean_404(self) -> None:
        base = self.start()
        code, body = self.get(f"{base}/definitely-not-a-route")
        self.assertEqual(code, 404)
        self.assertIn("unknown route", body["error"])

    def test_an_occupied_control_port_cannot_be_shared_with_a_second_listener(self) -> None:
        base = self.start(token="original-test-token")
        port = int(base.rsplit(":", 1)[1])
        second = ControlServer(
            {"remote": {"enabled": True, "port": port, "token": "different-test-token"}},
            {"status_provider": lambda: {"app": "wrong-instance"}},
        )
        self.addCleanup(second.stop)
        second.start()
        self.assertFalse(second.running, "a second server shared the occupied port")
        code, body = self.get(base + "/status", token="original-test-token")
        self.assertEqual((code, body["app"]), (200, "running"))

    def test_stopped_control_server_can_start_again_on_its_configured_port(self) -> None:
        base = self.start()
        self.assertEqual(self.get(base + "/status")[0], 200)
        self.server.stop()
        self.server.start()
        self.assertTrue(self.server.running)
        self.assertEqual(self.get(base + "/status")[0], 200)

    def test_another_socket_cannot_force_its_way_onto_the_control_port(self) -> None:
        base = self.start(token="original-test-token")
        port = int(base.rsplit(":", 1)[1])
        with socket.socket() as other:
            other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with self.assertRaises(OSError):
                other.bind(("127.0.0.1", port))
                other.listen(1)
        code, body = self.get(base + "/status", token="original-test-token")
        self.assertEqual((code, body["app"]), (200, "running"))

    def test_a_rebound_hostname_cannot_drive_the_api(self) -> None:
        base = self.start()
        code, body = self.get(f"{base}/toggle", host="evil.example")
        self.assertEqual(code, 403)
        self.assertIn("localhost", body["error"])
        self.assertEqual(self.calls, [], "a non-loopback Host reached a callback")

    def test_a_web_page_cannot_start_the_microphone(self) -> None:
        """X-193: the whole attack, in one request.

        Binding to loopback is not an access control -- the browser on this
        machine reaches 127.0.0.1 as happily as anything else does. Any page
        the user visited could fire this and start recording them. It needed no
        token (these routes have never had one), no CORS (the damage is the
        side effect, so an opaque no-cors request is enough), and it left no
        trace: no prompt, no log line, nothing on screen but the pill going
        live while they read someone else's website.
        """
        base = self.start()
        code, body = self.get(f"{base}/toggle", sec_fetch_site="cross-site")
        self.assertEqual(code, 403)
        self.assertIn("web pages", body["error"])
        self.assertEqual(self.calls, [], "a web page started the microphone")

    def test_a_page_on_another_localhost_port_is_also_a_web_page(self) -> None:
        """same-site, not cross-site: a different port is a different ORIGIN
        but the same SITE, which is how a hostile local page or a forgotten dev
        server on this machine would reach us."""
        base = self.start()
        code, _body = self.get(f"{base}/paste-last", sec_fetch_site="same-site")
        self.assertEqual(code, 403)
        self.assertEqual(self.calls, [])

    def test_real_automation_still_works_untouched(self) -> None:
        """The rule is default-ALLOW, and this is why.

        curl, the app's own CLI, AutoHotkey, Stream Deck and Raycast send no
        Sec-Fetch-* header at all. A browser extension service worker sends
        "none". If any of those broke, every documented automation in the
        product would have broken with them, silently, on update.
        """
        base = self.start()
        self.assertEqual(self.get(f"{base}/toggle")[0], 200)                        # curl
        self.assertEqual(self.get(f"{base}/cancel", sec_fetch_site="none")[0], 200)  # extension
        self.assertEqual(
            self.get(f"{base}/paste-last", sec_fetch_site="same-origin")[0], 200
        )
        self.assertEqual(self.calls, ["hands_free", "panic", "paste_last"])

    def test_the_header_cannot_be_defeated_by_casing_or_padding(self) -> None:
        base = self.start()
        for value in ("Cross-Site", " cross-site ", "CROSS-SITE"):
            with self.subTest(value=value):
                self.assertEqual(self.get(f"{base}/toggle", sec_fetch_site=value)[0], 403)
        self.assertEqual(self.calls, [])

    def test_dictated_text_is_never_served_without_a_token(self) -> None:
        base = self.start()
        code, body = self.get(f"{base}/last-text")
        self.assertEqual(code, 403)
        self.assertIn("remote.token", body["error"])
        self.assertNotIn("secret", json.dumps(body))

    def test_token_gates_every_route_when_configured(self) -> None:
        base = self.start(token="your-test-token")
        self.assertEqual(self.get(f"{base}/status")[0], 401)
        self.assertEqual(self.get(f"{base}/toggle", token="wrong")[0], 401)
        self.assertEqual(self.calls, [])

        code, body = self.get(f"{base}/last-text", token="your-test-token")
        self.assertEqual(code, 200)
        self.assertEqual(body["text"], "the secret transcript")

    def test_a_non_ascii_token_is_compared_without_crashing(self) -> None:
        base = self.start(token="your-café-tøken")
        self.assertEqual(self.get(f"{base}/status")[0], 401)
        self.assertEqual(self.get(f"{base}/status", token="your-café-tøken")[0], 200)

    def test_token_may_also_travel_as_a_query_value(self) -> None:
        base = self.start(token="your-test-token")
        self.assertEqual(self.get(f"{base}/toggle?token=your-test-token")[0], 200)
        self.assertEqual(self.calls, ["hands_free"])

    def test_stop_releases_the_port(self) -> None:
        base = self.start()
        port = int(base.rsplit(":", 1)[1])
        self.server.stop()
        self.assertFalse(self.server.running)
        with socket.socket() as probe:
            probe.settimeout(2)
            self.assertNotEqual(probe.connect_ex(("127.0.0.1", port)), 0)


if __name__ == "__main__":
    unittest.main()


class AWebSocketIsStillAWebPageTests(unittest.TestCase):
    """X-209: the Sec-Fetch-Site guard had exactly one hole, and it was measured.

    Eight cross-origin vectors were fired from a real Edge browser at a real
    ControlServer. Seven carried `Sec-Fetch-Site: cross-site` and were refused.
    One carried no Sec-Fetch-* header at all:

        new WebSocket("ws://127.0.0.1:4670/toggle")

    A WebSocket handshake is a plain GET. BaseHTTPRequestHandler never inspects
    `Upgrade:`, so it ran as an ordinary GET, the callback fired, and the reply
    was a 200 the socket could not use. The handshake failing does not matter --
    the damage IS the side effect. Against the shipped default config the three
    action routes produced, verbatim:

        CALLBACKS FIRED: ['MIC TOGGLED', 'PASTED LAST TRANSCRIPT', 'panic']

    /paste-last is the worst: the attacking page holds focus, so it focuses a
    hidden input, fires the request, and reads the victim's last dictation out
    of the DOM -- the exact exfiltration the token gate on /last-text exists to
    stop, reached without a token.

    Raw sockets here rather than urllib, because urllib will not send an
    Upgrade header and the whole point is the bytes a browser actually sends.
    """

    WEBSOCKET_HANDSHAKE = (
        "Origin: http://localhost:47772\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: x3JJHMbDL1EzLkh9GBhXDw==\r\n"
        "Sec-WebSocket-Version: 13\r\n"
    )

    def setUp(self) -> None:
        self.fired: list[str] = []
        self.port = free_port()
        self.server = ControlServer(
            {"remote": {"enabled": True, "port": self.port}},
            {
                "hands_free": lambda: self.fired.append("hands_free"),
                "panic": lambda: self.fired.append("panic"),
                "paste_last": lambda: self.fired.append("paste_last"),
                "status_provider": lambda: {"app": "running"},
                "last_text": lambda: "the secret transcript",
            },
        )
        self.server.start()
        self.assertTrue(self.server.running)
        self.addCleanup(self.server.stop)

    def raw(self, route: str, extra_headers: str = "") -> str:
        import time

        connection = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        try:
            connection.sendall(
                (f"GET {route} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n" + extra_headers + "\r\n").encode()
            )
            time.sleep(0.2)
            try:
                reply = connection.recv(400).decode(errors="replace")
            except OSError:
                reply = ""
        finally:
            connection.close()
        return reply.splitlines()[0] if reply else ""

    def test_a_websocket_cannot_start_the_microphone(self) -> None:
        self.assertIn("403", self.raw("/toggle", self.WEBSOCKET_HANDSHAKE))
        self.assertEqual(self.fired, [], "a WebSocket handshake started the microphone")

    def test_a_websocket_cannot_exfiltrate_the_last_transcript(self) -> None:
        self.assertIn("403", self.raw("/paste-last", self.WEBSOCKET_HANDSHAKE))
        self.assertEqual(self.fired, [], "a WebSocket handshake pasted the last dictation")

    def test_a_clicked_link_cannot_fire_an_action(self) -> None:
        """Sec-Fetch-Site: none is a legitimate value for a user typing in the
        URL bar, so it stays allowed. A NAVIGATION is what a link in an email
        or a chat message produces, and it costs one click."""
        navigation = "Sec-Fetch-Site: none\r\nSec-Fetch-Mode: navigate\r\nSec-Fetch-Dest: document\r\n"
        self.assertIn("403", self.raw("/paste-last", navigation))
        self.assertEqual(self.fired, [])

    def test_an_ordinary_browser_origin_is_refused_even_with_no_sec_fetch(self) -> None:
        """Belt and braces for any browser or version that omits Sec-Fetch-*.
        No non-browser client sends Origin."""
        self.assertIn("403", self.raw("/toggle", "Origin: http://evil.example\r\n"))
        self.assertEqual(self.fired, [])

    def test_real_automation_is_untouched(self) -> None:
        """curl, the CLI, AutoHotkey, Stream Deck: no Origin, no Sec-Fetch-*,
        no Upgrade. If this ever fails, every documented automation broke."""
        self.assertIn("200", self.raw("/toggle"))
        self.assertEqual(self.fired, ["hands_free"])

    def test_the_browser_extension_is_untouched(self) -> None:
        """extension/background.js fetches 127.0.0.1:4670 from a service
        worker, which sends a chrome-extension:// Origin."""
        extension = "Origin: chrome-extension://abcdefghijklmnopabcdefghijklmnop\r\nSec-Fetch-Site: none\r\n"
        self.assertIn("200", self.raw("/cancel", extension))
        self.assertEqual(self.fired, ["panic"])

    def test_the_refusal_says_which_signal_caught_it(self) -> None:
        """Three rules now. Without a reason, the next person debugging a
        broken automation cannot tell which one they tripped."""
        from knight_flow.http_api import _browser_fingerprint

        class Headers(dict):
            def get(self, key, default=""):
                return dict.get(self, key.lower(), default)

        self.assertEqual(_browser_fingerprint(Headers(upgrade="websocket")), "protocol upgrade")
        self.assertEqual(_browser_fingerprint(Headers({"sec-fetch-site": "cross-site"})), "page request")
        self.assertEqual(_browser_fingerprint(Headers({"sec-fetch-mode": "navigate"})), "browser navigation")
        self.assertEqual(_browser_fingerprint(Headers(origin="http://evil.example")), "browser origin")
        self.assertEqual(_browser_fingerprint(Headers()), "")
