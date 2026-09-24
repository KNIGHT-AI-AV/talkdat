"""Sign-in for Talk DAT!: local verification of the signed account token.

2026-09-22: Talk DAT! is free. Nothing here decides whether anybody may
dictate -- there is no plan, trial, allowance or purchase to check. What is
left is the account: signing this computer in (browser device flow or the
emailed six-digit code), verifying the signed token that proves it, and
signing out again. The account service sees account and device metadata only.
Audio, transcripts, dictionaries, provider keys and local model data never
enter this path.
"""

from __future__ import annotations

from . import mac_support

import base64
import json
import os
import platform
import secrets
import sys
import time
from contextlib import suppress
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import official_build
from .credentials import CredentialStore, credential_store, credential_target


LICENSE_AUDIENCE = "talk-dat-desktop"
LICENSE_ISSUER = "https://talkdat.app"
LICENSE_TARGET = credential_target("License", "entitlement")
# Where the account service actually answers.
#
# The service runs on Railway under the product's own domain since September
# 2026; before that it was a generated Cloud Run hostname, and before THAT it
# was `https://api.talkdat.knightaiav.com`, a hostname that never existed: no
# domain mapping, no DNS record. Every account operation the desktop performs
# -- device activation, trial start, entitlement refresh, managed cloud -- was
# failing before it left the machine, and reporting "could not reach the
# account service", which reads like the user's network rather than a wrong
# address.
#
# The website calls the same address; it is in the site's own CSP connect-src
# (the Railway site's Caddyfile, mirrored in the legacy firebase.json). If this ever changes
# again, confirm the new name resolves FIRST, then change it here and in the
# CSP in the same commit, or the browser half breaks instead.
# tests/test_the_hosts_are_talkdat_app.py pins the two halves together.
#
# 2026-09-23 (open source): the literal lives in official_build.py, the one
# module that decides whether this build may contact Knight at all. This name
# stays as the OFFICIAL address; what a given build actually uses is
# official_build.api_base(config), which is "" in a source build.
DEFAULT_COMMERCE_API_URL = official_build.KNIGHT_API_BASE
DEFAULT_PRODUCT_URL = official_build.KNIGHT_PRODUCT_URL
PUBLIC_KEY_PATH = Path(__file__).resolve().parent / "assets" / "license_public_key.pem"


class LicenseError(RuntimeError):
    pass


@dataclass(frozen=True)
class LicenseState:
    plan: str = "none"
    status: str = "not_activated"
    active: bool = False
    permanent_core: bool = False
    needs_refresh: bool = False
    email: str = ""
    expires_at: int = 0
    detail: str = "Not signed in. Dictation works the same either way."

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _decode_segment(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise LicenseError("The saved license token is malformed.") from exc


def verify_license_token(
    token: str,
    *,
    device_id: str,
    public_key_pem: bytes,
    now: int | None = None,
) -> LicenseState:
    parts = str(token or "").split(".")
    if len(parts) != 3:
        raise LicenseError("The saved license token is malformed.")
    try:
        header = json.loads(_decode_segment(parts[0]))
        payload = json.loads(_decode_segment(parts[1]))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise LicenseError("The saved license token is malformed.") from exc
    if header.get("alg") != "EdDSA" or header.get("typ") != "JWT":
        raise LicenseError("The license signature type is not supported.")
    try:
        key = serialization.load_pem_public_key(public_key_pem)
        if not isinstance(key, Ed25519PublicKey):
            raise TypeError("not ed25519")
        key.verify(_decode_segment(parts[2]), f"{parts[0]}.{parts[1]}".encode("ascii"))
    except (InvalidSignature, TypeError, ValueError) as exc:
        raise LicenseError("The saved license signature is invalid.") from exc
    if payload.get("iss") != LICENSE_ISSUER or payload.get("aud") != LICENSE_AUDIENCE:
        raise LicenseError("The saved license belongs to another product.")
    if payload.get("device_id") != device_id:
        raise LicenseError("The saved license belongs to another PC activation.")
    timestamp = int(time.time() if now is None else now)
    if int(payload.get("nbf", 0) or 0) > timestamp + 60:
        raise LicenseError("The saved license is not active yet.")
    # `plan` is read for compatibility with tokens the service already issued.
    # It is not shown and gates nothing: Talk DAT! is free (2026-09-22).
    raw_plan = str(payload.get("plan") or "free")
    plan = raw_plan if raw_plan in {"lifetime", "pro", "trial", "free"} else "free"
    permanent_core = bool(payload.get("permanent_core")) and plan == "lifetime"
    email = str(payload.get("email") or "")
    signed_in = f"Signed in as {email}." if email else "Signed in."
    expires_at = int(payload.get("exp", 0) or 0)
    expired = expires_at <= timestamp
    status = str(payload.get("status") or "unknown")
    if permanent_core:
        return LicenseState(
            plan=plan,
            status=status,
            active=True,
            permanent_core=True,
            needs_refresh=expired,
            email=email,
            expires_at=expires_at,
            detail=signed_in if not expired else f"{signed_in} Account details need an online refresh.",
        )
    active = status == "active" and not expired
    return LicenseState(
        plan=plan,
        status="active" if active else "expired",
        active=active,
        permanent_core=False,
        needs_refresh=False,
        email=email,
        expires_at=expires_at,
        detail=signed_in if active else "Your sign-in needs a refresh. Sign in again; dictation keeps working meanwhile.",
    )


def ensure_device_identity(config: dict[str, Any]) -> str:
    licensing = config.setdefault("licensing", {})
    device_id = str(licensing.get("device_id") or "").strip()
    if not device_id:
        device_id = f"td-{uuid.uuid4()}"
        licensing["device_id"] = device_id
    return device_id


class LicenseManager:
    def __init__(
        self,
        config: dict[str, Any],
        *,
        store: CredentialStore | None = None,
        opener: Callable[..., Any] = urlopen,
        public_key_pem: bytes | None = None,
    ) -> None:
        settings = config.setdefault("licensing", {})
        self.device_id = ensure_device_identity(config)
        self.device_name = str(settings.get("device_name") or platform.node() or mac_support.UNNAMED_DEVICE_LABEL)[:80]
        # "" in a source build that has not been pointed at an account
        # service: every request below then refuses before it is built.
        self.api_base = official_build.api_base(config)
        self.product_url = str(settings.get("product_url") or DEFAULT_PRODUCT_URL).rstrip("/")
        self.store = store or credential_store()
        self.opener = opener
        self.public_key_pem = public_key_pem if public_key_pem is not None else PUBLIC_KEY_PATH.read_bytes()

    def status(self) -> LicenseState:
        token = self.store.read(LICENSE_TARGET) if self.store.available else ""
        if not token:
            return LicenseState()
        try:
            return verify_license_token(token, device_id=self.device_id, public_key_pem=self.public_key_pem)
        except LicenseError as exc:
            return LicenseState(status="invalid", detail=str(exc))

    def forget_license(self) -> bool:
        """Remove the signed account token from this device.

        Deletes this one target rather than calling delete_all_credentials(),
        because signing out must not also throw away the person's own
        provider keys.

        X-194: this used to erase the token by WRITING AN EMPTY STRING, and the
        credential store refuses an empty secret before it ever reaches
        CredWriteW (credentials.py: `if ... not secret: return False`). So the
        write returned False, nothing was deleted, and Sign out failed on every
        Windows machine there has ever been -- reporting "Windows Credential
        Manager was unavailable" while the vault was working perfectly. The
        entitlement, and the account identity inside it, stayed on the PC for
        whoever got it next.

        Three tests covered this and all three stubbed forget_license with a
        lambda, so the bug outlived them.
        """
        if not self.store.available:
            return False
        with suppress(Exception):
            # delete() treats ERROR_NOT_FOUND as success, so signing out twice
            # is idempotent rather than a spurious failure.
            return bool(self.store.delete(LICENSE_TARGET))
        return False

    def begin_activation(self) -> dict[str, Any]:
        return self._json_request(
            "/v1/device/start",
            {"deviceId": self.device_id, "deviceName": self.device_name},
        )

    def exchange_activation(self, *, user_code: str, device_code: str) -> LicenseState:
        result = self._json_request(
            "/v1/device/token",
            {"userCode": user_code, "deviceCode": device_code},
        )
        return self._accept_license(result)

    # ------------------------------------------------------------- X-432
    # The emailed-code sign-in, run by the app. Each of these is one of the
    # calls the website makes on the account page; the app makes them in the
    # same order and ends in the same exchange_activation as the browser path.

    def start_email_code(self, email: str) -> dict[str, Any]:
        """Ask for a six-digit code at `email`. The account is created on
        first verify, so this is also how a new account begins."""
        cleaned = str(email or "").strip().lower()
        if "@" not in cleaned or "." not in cleaned.rsplit("@", 1)[-1]:
            raise LicenseError("Enter the email address you want the code sent to.")
        # The route insists on a 32-hex request id, the same as the website's.
        return self._json_request(
            "/v1/auth/email/start",
            {"email": cleaned, "requestId": secrets.token_hex(16), "client": self.client_label},
        )

    def verify_email_code(self, email: str, code: str) -> dict[str, Any]:
        """Trade the six digits for a session. Returns the service's session
        (accessToken, refreshToken, user); nothing is stored here."""
        digits = "".join(ch for ch in str(code or "") if ch.isdigit())
        if len(digits) != 6:
            raise LicenseError("Enter the six digits from the email.")
        return self._json_request(
            "/v1/auth/email/verify",
            {"email": str(email or "").strip().lower(), "code": digits, "client": self.client_label},
        )

    def approve_device(self, access_token: str, user_code: str) -> dict[str, Any]:
        """Approve THIS device's pending code as the signed-in account, which
        is what the website does when the person clicks Activate this
        computer. The licence itself
        still comes from exchange_activation, exactly as after a browser
        approval, so the acceptance path is one path."""
        if not access_token:
            raise LicenseError("Sign in first, then activate this computer.")
        return self._json_request("/v1/device/approve", {"userCode": user_code}, bearer=access_token)

    @property
    def client_label(self) -> str:
        return "talkdat-mac" if sys.platform == "darwin" else "talkdat-windows"

    def adopt_handoff(self, result: dict[str, Any]) -> LicenseState:
        """X-11: accept a licence delivered by the web handoff -- the same
        acceptance path every other activation uses."""
        return self._accept_license(result)

    def _accept_license(self, result: dict[str, Any]) -> LicenseState:
        token = str(result.get("licenseToken") or "")
        state = verify_license_token(token, device_id=self.device_id, public_key_pem=self.public_key_pem)
        if not self.store.available or not self.store.write(LICENSE_TARGET, token):
            raise LicenseError(f"{mac_support.CREDENTIAL_VAULT_NAME} could not save the signed license.")
        return state

    def _json_request(self, path: str, body: dict[str, Any], *, bearer: str = "") -> dict[str, Any]:
        if not getattr(self, "api_base", ""):
            raise LicenseError(official_build.SIGN_IN_OFF)
        headers = {"content-type": "application/json", "user-agent": mac_support.USER_AGENT}
        if bearer:
            headers["authorization"] = f"Bearer {bearer}"
        request = Request(
            f"{self.api_base}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with self.opener(request, timeout=15) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                message = str(payload.get("message") or payload.get("error") or exc.reason)
                code = str(payload.get("error") or "")
            except Exception:
                message, code = str(exc.reason), ""
            error = LicenseError(message or "Account activation failed.")
            setattr(error, "code", code)
            raise error from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise LicenseError("Talk DAT! could not reach the account service. Core local dictation is unaffected.") from exc
        if not isinstance(result, dict):
            raise LicenseError("The account service returned an invalid response.")
        return result
