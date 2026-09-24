"""Opt-in local control API for automation (Stream Deck, AutoHotkey, Raycast-style launchers).

Binds to 127.0.0.1 only. Enable via config remote.enabled; if remote.token is
set, requests must send it as a Bearer token or ?token= query value.

Endpoints: GET /status, POST (or GET) /toggle /cancel /paste-last /copy-last.

Two rules keep a loopback listener from becoming a way out of the browser sandbox:

* Every request must address this server as localhost. A page the user visits can
  point a hostname it controls at 127.0.0.1 and then script requests to it (DNS
  rebinding); that request still carries the attacker's hostname in `Host`, so
  checking it rejects the page while leaving real 127.0.0.1 clients alone.
* `/last-text` returns dictated content, so it always requires a token even though
  the action routes stay usable without one for existing automation setups.
"""

from __future__ import annotations

import hmac
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def host_is_loopback(host_header: str) -> bool:
    """True when a Host header addresses this machine's loopback interface."""
    host = (host_header or "").strip()
    if not host:
        # HTTP/1.1 requires Host. Anything without one is not a browser and not a
        # normal client; refuse rather than guess.
        return False
    if host.startswith("["):
        host = host.partition("]")[0] + "]"
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    return host.lower() in LOOPBACK_HOSTS


# X-193: binding to loopback is not an access control.
#
# A browser on this machine reaches 127.0.0.1 as happily as any other host, so
# every page the user visited could POST /toggle to start their microphone, or
# /paste-last to push their last dictation into whatever window had focus. No
# token was required for those routes, no prompt appeared, and nothing was
# logged. The page never needed to read a response -- the damage is the side
# effect, so an opaque no-cors request was enough and CORS never entered it.
#
# Sec-Fetch-Site is the one signal a page cannot launder. It is a forbidden
# header name, so script cannot set, forge, or strip it, and the browser
# attaches it to every subresource request -- fetch, <img>, <form>, <script>.
#
# The rule is deliberately default-ALLOW rather than default-deny. curl, the
# app's own CLI, AutoHotkey, Stream Deck and Raycast send no Sec-Fetch-* header
# at all, so they present "" and are untouched; every documented automation
# keeps working with no migration and no new setting. Extension service
# workers present "none", which is also allowed, so the shipped companion
# extension keeps working.
#
# What is refused is exactly what a browser labels as coming from a page:
# "cross-site" (evil.example) and "same-site" (another port on localhost, which
# is a different origin but the same site, and is how a hostile local page or a
# stale dev server would reach us).
WEB_PAGE_INITIATED = frozenset({"cross-site", "same-site"})

# X-209: Sec-Fetch-Site alone was NOT enough, and the gap was measured.
#
# Firing eight cross-origin vectors from a real Edge browser at a real
# ControlServer, seven carried `Sec-Fetch-Site: cross-site` and were refused:
# fetch, fetch/no-cors, POST, <img>, <script>, sendBeacon, EventSource and a
# <form> POST. ONE carried no Sec-Fetch-* header at all:
#
#     new WebSocket("ws://127.0.0.1:4670/toggle")
#
# A WebSocket handshake is a plain `GET /toggle HTTP/1.1`. BaseHTTPRequestHandler
# never looks at `Upgrade:`, so it is handled as an ordinary GET, the callback
# fires, and the reply is a 200 the socket cannot use. The handshake failing is
# irrelevant -- the damage is the side effect, and it already happened. Against
# the shipped default config this produced, verbatim:
#
#     CALLBACKS FIRED: ['MIC TOGGLED', 'PASTED LAST TRANSCRIPT', 'panic']
#
# /paste-last is the worst of the three: the attacking page holds focus, so it
# can focus a hidden input, fire the request, and read the user's last
# dictation straight out of the DOM. That is the exact exfiltration the token
# gate on /last-text exists to prevent, walked around without a token.
#
# Two more signals close it, both things no non-browser client ever sends:
#
#   Upgrade / Connection: upgrade -- this is not a WebSocket server. There is
#     no legitimate caller that asks it to become one.
#   Origin -- browsers attach it to every WebSocket handshake and every
#     cross-origin request. curl, the app's own CLI, AutoHotkey, Stream Deck
#     and Raycast attach nothing. The shipped browser extension does send one,
#     so extension origins stay allowed by name.
#
# Sec-Fetch-Mode: navigate covers the last vector: a link in an email or a chat
# message pointing at http://127.0.0.1:4670/paste-last, which fires on one
# click and shows the victim a JSON blob afterwards.
EXTENSION_ORIGIN_SCHEMES = ("chrome-extension://", "moz-extension://", "safari-web-extension://")


def _is_extension_origin(origin: str) -> bool:
    value = (origin or "").strip().lower()
    return any(value.startswith(scheme) for scheme in EXTENSION_ORIGIN_SCHEMES)


def _looks_like_a_web_page(sec_fetch_site: str) -> bool:
    """True when the BROWSER says this request came from a page on some site."""
    return (sec_fetch_site or "").strip().lower() in WEB_PAGE_INITIATED


def _browser_fingerprint(headers: Any) -> str:
    """Why this request looks like it came from a browser, or "" if it does not.

    Returns a reason rather than a bool so the refusal can say which signal
    fired -- otherwise the next person debugging a broken automation has three
    rules and no way to tell which one caught them.
    """
    def get(name: str) -> str:
        try:
            return str(headers.get(name, "") or "").strip().lower()
        except Exception:
            return ""

    if get("upgrade") or "upgrade" in get("connection"):
        return "protocol upgrade"
    if _looks_like_a_web_page(get("sec-fetch-site")):
        return "page request"
    if get("sec-fetch-mode") == "navigate" or get("sec-fetch-dest") == "document":
        return "browser navigation"
    origin = get("origin")
    if origin and not _is_extension_origin(origin):
        return "browser origin"
    return ""


class _ControlHTTPServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR permits another listener to share an active port.
    # Keep normal restart semantics elsewhere, but reserve this Windows endpoint
    # exclusively so a second process cannot receive this instance's requests.
    allow_reuse_address = os.name != "nt"
    allow_reuse_port = False

    def server_bind(self) -> None:
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class ControlServer:
    def __init__(self, config: dict[str, Any], callbacks: dict[str, Any]) -> None:
        self.config = config
        self.callbacks = callbacks
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> None:
        remote = self.config.get("remote", {})
        if not remote.get("enabled", False) or self.running:
            return
        port = int(remote.get("port", 4670))
        token = str(remote.get("token", "")).strip()
        callbacks = self.callbacks

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                pass

            def _presented_token(self, query: dict[str, list[str]]) -> str:
                header = self.headers.get("Authorization", "")
                if header.startswith("Bearer "):
                    return header[len("Bearer ") :]
                return query.get("token", [""])[0]

            def _authorized(self, query: dict[str, list[str]]) -> bool:
                if not token:
                    return True
                # Compare as bytes: compare_digest rejects non-ASCII str arguments, and
                # a user is free to put any character in remote.token.
                return hmac.compare_digest(
                    self._presented_token(query).encode("utf-8"), token.encode("utf-8")
                )

            def _respond(self, code: int, body: dict[str, Any]) -> None:
                payload = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _handle(self) -> None:
                if not host_is_loopback(self.headers.get("Host", "")):
                    self._respond(403, {"error": "this API only answers to localhost"})
                    return
                looks_like_a_browser = _browser_fingerprint(self.headers)
                if looks_like_a_browser:
                    self._respond(
                        403,
                        {
                            "error": "this API does not answer requests from web pages",
                            "refused": looks_like_a_browser,
                        },
                    )
                    return
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                if not self._authorized(query):
                    self._respond(401, {"error": "unauthorized"})
                    return
                route = parsed.path.rstrip("/") or "/status"
                actions = {
                    "/toggle": "hands_free",
                    "/cancel": "panic",
                    "/paste-last": "paste_last",
                    "/copy-last": "copy_last",
                }
                if route == "/status":
                    snapshot = callbacks.get("status_provider")
                    self._respond(200, snapshot() if callable(snapshot) else {"app": "running"})
                    return
                if route == "/last-text":
                    # This is the only route that hands back dictated content, so it is
                    # never available on a tokenless listener.
                    if not token:
                        self._respond(
                            403,
                            {"error": "set remote.token before reading dictated text"},
                        )
                        return
                    provider = callbacks.get("last_text")
                    self._respond(200, {"text": provider() if callable(provider) else ""})
                    return
                action = actions.get(route)
                if action and callable(callbacks.get(action)):
                    callbacks[action]()
                    self._respond(200, {"ok": True, "action": action})
                    return
                self._respond(404, {"error": f"unknown route {route}"})

            def do_GET(self) -> None:  # noqa: N802
                self._handle()

            def do_POST(self) -> None:  # noqa: N802
                self._handle()

        try:
            self._server = _ControlHTTPServer(("127.0.0.1", port), Handler)
        except OSError:
            self._server = None
            return
        self._thread = threading.Thread(target=self._server.serve_forever, name="TalkDatControlAPI", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
