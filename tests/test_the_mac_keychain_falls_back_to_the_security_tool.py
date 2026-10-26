"""Polylane iss_166dd7d14001b2pzwfznwqhj: on a Mac, a keyring that is not the macOS Keychain must not swallow every secret.

X-433 made MacKeychainStore prefer `keyring` over the `security` tool, so a
secret never has to sit in argv. But it took keyring whenever it IMPORTED.
keyring can import and still resolve to its fail or null backend (a frozen app
whose backend discovery found nothing), and then every read came back "" and
every write came back False, with no fallback to /usr/bin/security: sign-in
could not finish (the licence acceptor refuses a store that cannot write) and
provider keys stayed in plaintext config.json. keyring is used now only when
its backend is the macOS Keychain; anything else, or no keyring at all, means
the `security` tool, which is on every Mac.

These run on any platform: sys.platform reads "darwin", keyring is a fake
module, and subprocess.run is a fake `security` that keeps a dict.
"""

from __future__ import annotations

import contextlib
import sys
import types
import unittest
from unittest import mock

from knight_flow import credentials

TARGET = "TalkDat/License/entitlement"


class _Done:
    def __init__(self, code: int, out: str = "") -> None:
        self.returncode, self.stdout = code, out


class FakeSecurity:
    """subprocess.run as the `security` tool would answer it, over a dict."""

    def __init__(self) -> None:
        self.vault: dict[str, str] = {}
        self.verbs: list[str] = []

    def __call__(self, argv, **_kwargs):
        args = list(argv)[1:]
        verb, opts = args[0], dict(zip(args[1::2], args[2::2]))
        self.verbs.append(verb)
        service = opts.get("-s", "")
        if verb == "add-generic-password":
            self.vault[service] = opts["-w"]
            return _Done(0)
        if verb == "find-generic-password":
            return _Done(0, self.vault[service] + "\n") if service in self.vault else _Done(44)
        if verb == "delete-generic-password":
            return _Done(0) if self.vault.pop(service, None) is not None else _Done(44)
        return _Done(1)


def _backend(module: str):
    kind = type("Keyring", (), {})
    kind.__module__ = module
    return kind()


def fake_keyring(backend=None, broken_lookup: bool = False) -> types.ModuleType:
    """A keyring module whose calls work only when its backend is the macOS one, as the real fail backend raises."""
    module = types.ModuleType("keyring")
    module.vault = {}
    module.calls = []
    usable = backend is not None and type(backend).__module__ == "keyring.backends.macOS"

    def get_keyring():
        if broken_lookup:
            raise RuntimeError("no backend could be loaded")
        return backend

    def check() -> None:
        if not usable:
            raise RuntimeError("No recommended backend was available.")

    def get_password(service, name):
        module.calls.append("get")
        check()
        return module.vault.get(name)

    def set_password(service, name, secret):
        module.calls.append("set")
        check()
        module.vault[name] = secret

    def delete_password(service, name):
        module.calls.append("delete")
        check()
        module.vault.pop(name, None)

    module.get_keyring, module.get_password = get_keyring, get_password
    module.set_password, module.delete_password = set_password, delete_password
    return module


class TheMacStoreChoosesARealKeychainTests(unittest.TestCase):
    def setUp(self) -> None:
        credentials.MacKeychainStore.cache_clear()
        self.addCleanup(credentials.MacKeychainStore.cache_clear)

    @contextlib.contextmanager
    def mac(self, keyring_module):
        security = FakeSecurity()
        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch.dict(sys.modules, {"keyring": keyring_module}), \
                mock.patch("subprocess.run", security):
            store = credentials.MacKeychainStore()
            store.available = True  # the machine running the suite has no /usr/bin/security
            yield store, security

    def round_trip(self, store) -> None:
        self.assertEqual(store.read(TARGET), "")
        self.assertTrue(store.write(TARGET, "signed.token"), "the store refused to save the sign-in")
        self.assertEqual(store.read(TARGET), "signed.token")
        self.assertTrue(store.delete(TARGET))
        self.assertEqual(store.read(TARGET), "")

    def test_a_keyring_on_its_fail_backend_falls_back_to_the_security_tool(self) -> None:
        keyring = fake_keyring(_backend("keyring.backends.fail"))
        with self.mac(keyring) as (store, security):
            self.round_trip(store)
            self.assertIn("add-generic-password", security.verbs)
        self.assertEqual(keyring.calls, [], "a keyring that cannot store anything was still asked to")

    def test_a_keyring_on_its_null_backend_falls_back_too(self) -> None:
        with self.mac(fake_keyring(_backend("keyring.backends.null"))) as (store, security):
            self.round_trip(store)
            self.assertIn("add-generic-password", security.verbs)

    def test_a_keyring_that_cannot_name_its_backend_falls_back(self) -> None:
        with self.mac(fake_keyring(broken_lookup=True)) as (store, security):
            self.round_trip(store)
            self.assertIn("add-generic-password", security.verbs)

    def test_no_keyring_at_all_uses_the_security_tool(self) -> None:
        with self.mac(None) as (store, security):  # None in sys.modules makes the import fail
            self.round_trip(store)
            self.assertIn("add-generic-password", security.verbs)

    def test_the_macos_backend_is_used_and_the_secret_never_reaches_argv(self) -> None:
        """X-433 stays: with the real Keychain backend, the secret goes through keyring, never the tool's argv."""
        keyring = fake_keyring(_backend("keyring.backends.macOS"))
        with self.mac(keyring) as (store, security):
            self.round_trip(store)
            self.assertEqual(security.verbs, [])
        self.assertIn("set", keyring.calls)

    def test_a_chainer_holding_the_macos_backend_is_used(self) -> None:
        mac_backend = _backend("keyring.backends.macOS")
        chainer = _backend("keyring.backends.chainer")
        chainer.backends = [_backend("keyring.backends.fail"), mac_backend]
        keyring = fake_keyring(chainer)
        keyring_usable = fake_keyring(mac_backend)  # the chainer routes calls to the macOS backend
        keyring.set_password, keyring.get_password = keyring_usable.set_password, keyring_usable.get_password
        keyring.delete_password = keyring_usable.delete_password
        with self.mac(keyring) as (store, security):
            self.round_trip(store)
            self.assertEqual(security.verbs, [])


if __name__ == "__main__":
    unittest.main()
