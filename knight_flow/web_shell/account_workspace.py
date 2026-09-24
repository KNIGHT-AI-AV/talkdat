"""Account and sign-in, on the web shell (X-612).

The web Settings had an Account page that was a title and a "Manage account"
button, and the button opened the square Tk Account window: the one step of
signing in that never looked like the rest of Talk DAT!. The whole flow is
here now: email a six-digit code and type it, or sign in on the website with
the pairing code, cancel a wait, sign out. The sign-in itself is the app's own
(App.begin_email_sign_in, finish_email_sign_in, activate_license,
sign_out_license); this module only words the state for the page, exactly as
overlay.open_account did, and it never passes the device code on: the page
sees what a person needs to read, nothing a sign-in could be completed with.
"""
from __future__ import annotations

import re
import time
from typing import Any

WAITING = {"starting", "waiting"}
CODE_BOX = {"code_sent", "verifying", "code_error"}
POLLED = WAITING | {"verifying"}


def account_view(status: Any, activation: Any, now: float | None = None) -> dict[str, Any]:
    status = status if isinstance(status, dict) else {}
    activation = activation if isinstance(activation, dict) else {}
    now = time.time() if now is None else now
    email = str(status.get("email") or "")
    signed_in = bool(email) or bool(status.get("active")) or bool(status.get("permanent_core"))
    phase = str(activation.get("state") or "idle")
    view: dict[str, Any] = {"signed_in": signed_in, "email": email, "phase": phase, "code": "",
                            "code_box": phase in CODE_BOX, "waiting": phase in WAITING,
                            "note": "", "headline": "", "detail": "", "poll": phase in POLLED}
    if phase in WAITING:
        code = str(activation.get("user_code") or "")
        expires_at = float(activation.get("expires_at") or 0)
        remaining = max(0, int(expires_at - now)) if expires_at else 0
        clock = f" The code stays good for {remaining // 60}:{remaining % 60:02d}." if remaining else ""
        view.update(headline="Finish signing in, in your browser", code=code, detail=(
            "Your browser is open on the sign-in page. The code below is already filled in and "
            f"copied to your clipboard. This page updates itself when you are done.{clock}")
            if code else str(activation.get("detail") or "Preparing sign-in."))
    elif phase in CODE_BOX:
        view.update(headline="Checking your code" if phase == "verifying" else "Type the code from your email",
                    detail=str(activation.get("detail") or ""),
                    note=str(activation.get("detail") or "") if phase == "code_error" else "")
    elif phase == "error":
        view.update(headline="Sign-in did not finish", detail=str(activation.get("detail") or "Try again."))
    elif signed_in:
        view.update(headline=f"Signed in as {email}" if email else "Signed in",
                    detail=str(status.get("detail") or "This device is activated."))
    else:
        view.update(headline="Not signed in", detail=(
            "Sign in below with a code we email you, or on the website if you prefer. Dictation, "
            "the on-device models and your own API key work the same without an account."))
    return view


class AccountActions:
    """The app's own sign-in path, and nothing else."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def status(self) -> dict[str, Any]:
        return self.app.license_status()

    def activation(self) -> dict[str, Any]:
        return self.app.license_activation_status()

    def email_code(self, email: str) -> None:
        self.app.begin_email_sign_in(email)

    def verify_code(self, code: str) -> None:
        self.app.finish_email_sign_in(code)

    def browser_sign_in(self) -> None:
        self.app.activate_license()

    def cancel(self) -> None:
        self.app._license_activation_cancel.set()

    def sign_out(self) -> None:
        self.app.sign_out_license()

    def website(self) -> None:
        import sys
        import webbrowser

        base = str(self.app.config.get("licensing", {}).get("product_url") or "https://www.talkdat.app")
        # X-113 #12: only Windows registers the talkdat:// hand-off scheme.
        webbrowser.open(base + ("/?handoff=1#account" if sys.platform == "win32" else "/#account"))


class AccountWorkspace:
    OPERATIONS = frozenset({"status", "email_code", "verify_code", "browser_sign_in", "cancel", "sign_out", "website"})

    def __init__(self, actions: Any) -> None:
        self.actions = actions

    def handle(self, payload: Any) -> dict[str, Any]:
        if (type(payload) is not dict or payload.get("operation") not in self.OPERATIONS
                or not set(payload) <= {"operation", "value"}):
            raise ValueError("That account action is unavailable.")
        operation, value = payload["operation"], str(payload.get("value") or "").strip()
        if operation == "email_code":
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) or len(value) > 254:
                raise ValueError("Type the email address you want the code sent to.")
            self.actions.email_code(value)
        elif operation == "verify_code":
            code = re.sub(r"\s", "", value)
            if not re.fullmatch(r"\d{6}", code):
                raise ValueError("Type the six digits from your email.")
            self.actions.verify_code(code)
        elif operation != "status":
            getattr(self.actions, operation)()
        try:
            status, activation = self.actions.status(), self.actions.activation()
        except Exception:
            status, activation = {}, {"state": "error", "detail": "Your account status could not be read. Try again."}
        return account_view(status, activation)
