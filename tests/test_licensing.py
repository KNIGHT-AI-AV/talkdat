from __future__ import annotations

import base64
import json
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from knight_flow.licensing import (
    LICENSE_AUDIENCE,
    LICENSE_ISSUER,
    LICENSE_TARGET,
    LicenseError,
    LicenseManager,
    ensure_device_identity,
    verify_license_token,
)


class MemoryStore:
    available = True
    description = "test vault"

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, target: str) -> str:
        return self.values.get(target, "")

    def write(self, target: str, secret: str) -> bool:
        self.values[target] = secret
        return True

    def delete(self, target: str) -> bool:
        self.values.pop(target, None)
        return True


def encode(value: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")


def signed_token(private_key: Ed25519PrivateKey, device_id: str, **claims: object) -> str:
    now = int(time.time())
    header = encode({"alg": "EdDSA", "typ": "JWT", "kid": "test"})
    payload = encode(
        {
            "iss": LICENSE_ISSUER,
            "aud": LICENSE_AUDIENCE,
            "sub": "user-1",
            "email": "person@example.com",
            "device_id": device_id,
            "plan": "trial",
            "status": "active",
            "permanent_core": False,
            "iat": now,
            "nbf": now - 30,
            "exp": now + 3600,
            **claims,
        }
    )
    body = f"{header}.{payload}"
    signature = base64.urlsafe_b64encode(private_key.sign(body.encode())).decode().rstrip("=")
    return f"{body}.{signature}"


class LicensingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.private_key = Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    def test_device_identity_is_random_and_stable(self) -> None:
        config: dict = {"licensing": {}}
        first = ensure_device_identity(config)
        self.assertEqual(ensure_device_identity(config), first)
        self.assertRegex(first, r"^td-[0-9a-f-]{36}$")

    def test_valid_trial_token_is_device_bound(self) -> None:
        token = signed_token(self.private_key, "device-1")
        state = verify_license_token(token, device_id="device-1", public_key_pem=self.public_key)
        self.assertTrue(state.active)
        self.assertEqual(state.plan, "trial")
        with self.assertRaises(LicenseError):
            verify_license_token(token, device_id="device-2", public_key_pem=self.public_key)

    def test_expired_lifetime_keeps_permanent_core_active(self) -> None:
        token = signed_token(
            self.private_key,
            "device-1",
            plan="lifetime",
            permanent_core=True,
            exp=int(time.time()) - 10,
        )
        state = verify_license_token(token, device_id="device-1", public_key_pem=self.public_key)
        self.assertTrue(state.active)
        self.assertTrue(state.needs_refresh)
        self.assertTrue(state.permanent_core)

    def test_expired_trial_is_inactive(self) -> None:
        token = signed_token(self.private_key, "device-1", exp=int(time.time()) - 10)
        state = verify_license_token(token, device_id="device-1", public_key_pem=self.public_key)
        self.assertFalse(state.active)
        self.assertEqual(state.status, "expired")

    def test_pro_subscription_is_active_only_until_signed_expiry(self) -> None:
        active_token = signed_token(self.private_key, "device-1", plan="pro")
        active = verify_license_token(active_token, device_id="device-1", public_key_pem=self.public_key)
        self.assertTrue(active.active)
        self.assertEqual(active.plan, "pro")
        self.assertFalse(active.permanent_core)

        expired_token = signed_token(
            self.private_key,
            "device-1",
            plan="pro",
            exp=int(time.time()) - 10,
        )
        expired = verify_license_token(expired_token, device_id="device-1", public_key_pem=self.public_key)
        self.assertFalse(expired.active)
        self.assertEqual(expired.plan, "pro")

    def test_manager_verifies_before_saving_exchanged_token(self) -> None:
        store = MemoryStore()
        config = {"licensing": {"device_id": "device-1234567890", "api_base": "https://api.example"}}
        token = signed_token(self.private_key, "device-1234567890")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self) -> bytes:
                return json.dumps({"licenseToken": token}).encode()

        manager = LicenseManager(config, store=store, opener=lambda *_args, **_kwargs: Response(), public_key_pem=self.public_key)
        state = manager.exchange_activation(user_code="ABCD-EFGH", device_code="secret")
        self.assertTrue(state.active)
        self.assertEqual(store.values[LICENSE_TARGET], token)


class Answer:
    """What the account service answers, for a stand-in opener."""

    def __init__(self, body: dict) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.body).encode()


class RunNow:
    """threading.Thread that runs its target at start()."""

    def __init__(self, target, **_kwargs) -> None:
        self.target = target

    def start(self) -> None:
        self.target()


class TheDeviceNameIsNeverTheHostnameTests(unittest.TestCase):
    """The account service is told a plain label for this computer, "Mac" or "Windows PC", and never its network name,
    unless the person named the device themselves (licensing.device_name)."""

    HOSTNAME = "SAMS-MACBOOK-PRO"
    LABEL = "Mac" if sys.platform == "darwin" else "Windows PC"

    def sign_in_started(self, licensing: dict) -> str:
        sent: list[dict] = []

        def opener(request, timeout=0):
            sent.append(json.loads(request.data.decode("utf-8")))
            return Answer({"userCode": "ABCD-EFGH"})

        config = {"licensing": {"api_base": "https://api.example", **licensing}}
        with mock.patch("platform.node", return_value=self.HOSTNAME):
            LicenseManager(config, store=MemoryStore(), opener=opener, public_key_pem=b"").begin_activation()
        return sent[0]["deviceName"]

    def test_the_hostname_is_never_sent(self) -> None:
        self.assertEqual(self.sign_in_started({}), self.LABEL)

    def test_a_name_the_person_chose_is_kept(self) -> None:
        self.assertEqual(self.sign_in_started({"device_name": "Studio laptop"}), "Studio laptop")

    def test_the_web_sign_in_link_sends_the_same_name(self) -> None:
        from knight_flow import app

        sent: list[dict] = []

        def urlopen(request, timeout=0):
            sent.append(json.loads(request.data.decode("utf-8")))
            return Answer({"licenseToken": "signed"})

        config = {"licensing": {"api_base": "https://api.example", "device_id": "td-test"}}
        overlay = SimpleNamespace(root=SimpleNamespace(after=lambda _ms, run: run()), set_state=mock.Mock())
        with mock.patch("platform.node", return_value=self.HOSTNAME), mock.patch("urllib.request.urlopen", urlopen), \
                mock.patch.object(app.threading, "Thread", RunNow):
            manager = LicenseManager(config, store=MemoryStore(), public_key_pem=b"")
            manager.adopt_handoff = mock.Mock(return_value=SimpleNamespace(detail="Signed in."))
            app.TalkDatApp.complete_handoff(SimpleNamespace(config=config, license_manager=manager, overlay=overlay),
                                            "one-time-code")
        self.assertEqual(len(sent), 1, overlay.set_state.call_args)
        self.assertEqual(sent[0]["deviceName"], self.LABEL)
        manager.adopt_handoff.assert_called_once_with({"licenseToken": "signed"})


if __name__ == "__main__":
    unittest.main()
