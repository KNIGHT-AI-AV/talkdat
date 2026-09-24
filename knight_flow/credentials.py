"""Secure local storage for Talk DAT! provider credentials.

Windows uses the current user's Credential Manager. Other platforms retain the
existing config behavior until a native keychain backend is implemented.
"""

from __future__ import annotations

import copy
import ctypes
import logging
import os
import sys
import re
import sys
import threading
from ctypes import wintypes
from functools import lru_cache
from typing import Any, Protocol

log = logging.getLogger(__name__)

# Keychain groups entries by service; the per-secret "TalkDat/<scope>/<name>"
# target from credential_target() becomes the account within it.
KEYCHAIN_SERVICE = "TalkDat"


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
_HYDRATED_MARKER = "_credential_vault_hydrated"
# X-213: DERIVED, not hand-listed, because the hand-listed version drifted.
#
# These two tuples name every vault target `delete_all_credentials` can remove
# without being handed a config. They were maintained by hand beside two
# registries that grow, and they had fallen behind: "openrouter" and
# "talk_dat_cloud" were missing from the STT list, and "auto" and
# "talk_dat_cloud" from the LLM list.
#
# The consequence was a live provider key surviving the strongest factory
# reset. `_secret_groups` happily vaults TalkDat/LLM/auto when the AI-rewrite
# provider is "auto" -- which is the SHIPPED DEFAULT -- so pasting a key,
# later switching the provider to anything else, and then running "Everything,
# start completely over" left that key in Credential Manager for the next owner
# of the PC, with the dialog reporting a clean wipe.
#
# Deriving them means the next provider added to either registry cannot repeat
# it. "local" and "ollama" are excluded because they need no key, and "none"
# is not a provider.
def _vaultable_stt_ids() -> tuple[str, ...]:
    try:
        from .stt_registry import PROVIDER_BY_ID

        return tuple(sorted(set(PROVIDER_BY_ID) - {"local"}))
    except Exception:  # pragma: no cover - registry import cannot fail in practice
        return ("deepgram", "openai")


def _vaultable_llm_ids() -> tuple[str, ...]:
    try:
        from .llm import PROVIDER_DEFAULTS

        # "auto" is a real vault target: _secret_groups keys on the CONFIGURED
        # provider string, and "auto" is what the shipped default writes.
        return tuple(sorted(set(PROVIDER_DEFAULTS) - {"ollama"} | {"auto", "custom"}))
    except Exception:  # pragma: no cover
        return ("openai", "anthropic", "gemini", "groq", "custom", "auto")


class CredentialStore(Protocol):
    available: bool
    description: str

    def read(self, target: str) -> str: ...

    def write(self, target: str, secret: str) -> bool: ...

    def delete(self, target: str) -> bool: ...


class UnavailableCredentialStore:
    available = False
    description = "Secure credential storage unavailable; secrets remain in local config."

    def read(self, target: str) -> str:
        return ""

    def write(self, target: str, secret: str) -> bool:
        return False

    def delete(self, target: str) -> bool:
        return False


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(wintypes.BYTE)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_PCREDENTIALW = ctypes.POINTER(_CREDENTIALW)


class WindowsCredentialStore:
    available = os.name == "nt"
    description = "Protected by Windows Credential Manager for this Windows user."

    def __init__(self) -> None:
        self._api: Any | None = None
        if not self.available:
            return
        try:
            api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
            api.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
            api.CredWriteW.restype = wintypes.BOOL
            api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_PCREDENTIALW)]
            api.CredReadW.restype = wintypes.BOOL
            api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
            api.CredDeleteW.restype = wintypes.BOOL
            api.CredFree.argtypes = [ctypes.c_void_p]
            api.CredFree.restype = None
            self._api = api
        except (AttributeError, OSError):
            self.available = False

    def read(self, target: str) -> str:
        if not self.available or self._api is None or not target:
            return ""
        pointer = _PCREDENTIALW()
        if not self._api.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            return ""
        try:
            credential = pointer.contents
            if not credential.CredentialBlob or credential.CredentialBlobSize <= 0:
                return ""
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return raw.decode("utf-16-le")
        except (UnicodeDecodeError, ValueError):
            return ""
        finally:
            self._api.CredFree(pointer)

    def write(self, target: str, secret: str) -> bool:
        if not self.available or self._api is None or not target or not secret:
            return False
        raw = secret.encode("utf-16-le")
        if len(raw) > 2560:
            return False
        blob = ctypes.create_string_buffer(raw)
        credential = _CREDENTIALW()
        credential.Flags = 0
        credential.Type = CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.Comment = "Talk DAT! private provider credential"
        credential.CredentialBlobSize = len(raw)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(wintypes.BYTE))
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE
        credential.AttributeCount = 0
        credential.Attributes = None
        credential.TargetAlias = None
        credential.UserName = "Talk DAT!"
        return bool(self._api.CredWriteW(ctypes.byref(credential), 0))

    def delete(self, target: str) -> bool:
        if not self.available or self._api is None or not target:
            return False
        if self._api.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            return True
        return ctypes.get_last_error() == ERROR_NOT_FOUND


class KeychainCredentialStore:
    """macOS Keychain, reached through `keyring`.

    The `security` command-line tool would avoid the dependency but takes the
    secret as an argv element, where any process on the machine can read it out
    of `ps`. keyring calls the Security framework directly, so the secret never
    becomes a command line.

    Target strings are reused verbatim from the Windows store so a user's
    credentials keep the same names across platforms.
    """

    description = "Secrets are stored in your macOS Keychain."

    def __init__(self) -> None:
        self.available = False
        self._keyring: Any = None
        # Set once a read times out, so the remaining reads in the same startup
        # do not each wait for the same dialog.
        self._prompt_blocked = False
        if sys.platform != "darwin":
            return
        try:
            import keyring
            from keyring.backends import macOS as macos_backend

            # A machine with no usable Keychain (some CI images) silently gets a
            # fail backend, which would report success and lose the secret.
            if not isinstance(keyring.get_keyring(), macos_backend.Keyring):
                return
            self._keyring = keyring
            self.available = True
        except Exception:
            self.available = False

    def read(self, target: str) -> str:
        if not self.available:
            return ""
        # One timeout means a dialog is up, and it will still be up for the next
        # read. Thirteen secret groups are hydrated at startup, so waiting the
        # full timeout for each turned a four second delay into fifty-two --
        # measured at forty seconds of startup before this guard existed.
        # Whatever the user answers takes effect on the next launch either way.
        if self._prompt_blocked:
            return ""
        return self._read_without_hanging(target)

    def _read_without_hanging(self, target: str, timeout: float = 4.0) -> str:
        """Read one secret, giving up if macOS puts a dialog in the way.

        Secrets are hydrated while the configuration loads, which happens before
        any window exists. If the Keychain decides to ask permission first, the
        read blocks inside SecItemCopyMatching until somebody answers, and the
        app is frozen with no window, no Pill and nothing in the log -- it looks
        broken rather than blocked. Observed for real: a rebuild changes the
        ad-hoc signature, the existing item's ACL no longer matches, and every
        launch hung on a prompt.

        The dialog is not dismissed here and the user's answer is not
        second-guessed; the read is simply abandoned so startup continues. A
        missing key surfaces as "this provider needs its key", which the user can
        see and act on, rather than as an application that never opens.
        """
        result: list[str] = []
        error: list[BaseException] = []

        def fetch() -> None:
            try:
                result.append(self._keyring.get_password(KEYCHAIN_SERVICE, target) or "")
            except BaseException as exc:  # noqa: BLE001 - re-raised shape below
                error.append(exc)

        worker = threading.Thread(target=fetch, name="TalkDatKeychainRead", daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            self._prompt_blocked = True
            log.warning(
                "keychain read for %s did not finish in %.0fs; continuing without it and "
                "skipping the rest. macOS is probably asking permission -- answering it "
                "and restarting will pick the secrets up.",
                target,
                timeout,
            )
            return ""
        if error:
            log.warning("keychain read for %s failed: %s", target, error[0])
            return ""
        return result[0] if result else ""

    def write(self, target: str, secret: str) -> bool:
        if not self.available or self._prompt_blocked:
            return False
        return self._call_without_hanging(
            "write", target, lambda: self._keyring.set_password(KEYCHAIN_SERVICE, target, secret)
        )

    def delete(self, target: str) -> bool:
        if not self.available or self._prompt_blocked:
            return False
        return self._call_without_hanging(
            "delete", target, lambda: self._keyring.delete_password(KEYCHAIN_SERVICE, target)
        )

    def _call_without_hanging(self, verb: str, target: str, action: Any, timeout: float = 4.0) -> bool:
        """Same bound as reads, for the same reason.

        Guarding only `read` was not enough and made the symptom worse rather
        than better: a read that gives up returns "", the caller concludes the
        secret is absent and immediately writes or deletes it, and that call
        blocks on the very same dialog. Startup then hung inside SecItemDelete
        instead of SecItemCopyMatching -- a different stack, the same frozen app
        with no window.
        """
        done: list[bool] = []

        def run() -> None:
            try:
                action()
                done.append(True)
            except Exception:
                done.append(False)

        worker = threading.Thread(target=run, name=f"TalkDatKeychain{verb.title()}", daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            self._prompt_blocked = True
            log.warning(
                "keychain %s for %s did not finish in %.0fs; continuing without it and "
                "skipping the rest. macOS is probably asking permission -- answering it "
                "and restarting will pick the secrets up.",
                verb,
                target,
                timeout,
            )
            return False
        return bool(done and done[0])


@lru_cache(maxsize=1)
class MacKeychainStore:
    """X-432: the login keychain, through the system `security` tool.

    Until this existed, credential_store() answered Unavailable on the Mac and
    the licence acceptor refuses an unavailable store, so no sign-in of any
    kind could finish there: the browser flow, the forever code, and the
    in-app flow this shipped with. The port handoff planned `keyring`; the
    Mac's venv does not carry it, and `/usr/bin/security` is on every Mac.

    Items are generic passwords under the account name below, with the
    target as the service, which is the same TalkDat/<scope>/<name> shape
    Windows uses. `-U` on write updates in place, so a second sign-in never
    leaves two entries. Exit 44 from find is "not found" and reads as empty,
    exactly as the Windows store treats ERROR_NOT_FOUND.

    X-433: the secret is passed on the command line for the write, and the Mac
    port's KeychainCredentialStore refuses this approach for that reason: any
    process on the machine can read argv out of `ps`. What is stored here is a
    signed entitlement bound to this device id, which limits the damage, but
    limits is not none. So this store is the LAST resort: when `keyring` is
    importable it is used instead (the same library the Mac port ships), and
    this class only runs where keyring is absent.
    """

    account = "talkdat"
    description = "Protected by the macOS login keychain for this user."

    def __init__(self, runner: Any | None = None) -> None:
        import shutil
        import subprocess

        self._tool = shutil.which("security") or "/usr/bin/security"
        self._run = runner or (lambda args: subprocess.run(
            [self._tool, *args], capture_output=True, text=True, timeout=10, check=False))
        self.available = sys.platform == "darwin" and os.path.exists(self._tool)
        self._keyring: Any = None
        if runner is None and sys.platform == "darwin":
            try:
                import keyring  # the Security framework directly; no argv

                self._keyring = keyring
                self.description = "Secrets are stored in your macOS Keychain."
            except Exception:
                self._keyring = None

    def read(self, target: str) -> str:
        if not self.available or not target:
            return ""
        if self._keyring is not None:
            try:
                return self._keyring.get_password(self.account, target) or ""
            except Exception:
                return ""
        try:
            done = self._run(["find-generic-password", "-a", self.account, "-s", target, "-w"])
        except Exception:
            return ""
        return done.stdout.strip() if done.returncode == 0 else ""

    def write(self, target: str, secret: str) -> bool:
        if not self.available or not target or not secret:
            return False
        if self._keyring is not None:
            try:
                self._keyring.set_password(self.account, target, secret)
                return True
            except Exception:
                return False
        try:
            done = self._run(["add-generic-password", "-a", self.account, "-s", target, "-w", secret, "-U"])
        except Exception:
            return False
        return done.returncode == 0

    def delete(self, target: str) -> bool:
        if not self.available or not target:
            return False
        if self._keyring is not None:
            try:
                self._keyring.delete_password(self.account, target)
                return True
            except Exception as error:
                # keyring raises PasswordDeleteError for a missing item; deleting
                # twice is idempotent here, as on Windows.
                return type(error).__name__ == "PasswordDeleteError"
        try:
            done = self._run(["delete-generic-password", "-a", self.account, "-s", target])
        except Exception:
            return False
        # 44 is "not found": deleting twice is idempotent, as on Windows.
        return done.returncode in (0, 44)


def credential_store() -> CredentialStore:
    if os.name == "nt":
        store = WindowsCredentialStore()
        if store.available:
            return store
    # mac-port: reconcile with MacKeychainStore (X-432, main's dependency-
    # free twin) when main and mac-port next meet.
    elif sys.platform == "darwin":
        keychain = KeychainCredentialStore()
        if keychain.available:
            return keychain
    return UnavailableCredentialStore()


def credential_target(scope: str, name: str) -> str:
    clean_scope = re.sub(r"[^A-Za-z0-9._-]+", "-", str(scope).strip()).strip("-") or "General"
    clean_name = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name).strip()).strip("-") or "default"
    return f"TalkDat/{clean_scope}/{clean_name}"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _secret_groups(config: dict[str, Any]) -> list[tuple[str, list[tuple[dict[str, Any], str]]]]:
    groups: list[tuple[str, list[tuple[dict[str, Any], str]]]] = []
    stt = _dict(config.get("stt"))
    providers = _dict(stt.get("providers"))
    deepgram = _dict(config.get("deepgram"))
    provider_ids = list(providers)
    if deepgram and "deepgram" not in provider_ids:
        provider_ids.insert(0, "deepgram")
    for provider_id in provider_ids:
        settings = _dict(providers.get(provider_id))
        refs: list[tuple[dict[str, Any], str]] = []
        if settings:
            refs.append((settings, "api_key"))
        if provider_id == "deepgram" and deepgram:
            refs.append((deepgram, "api_key"))
        if refs and provider_id != "local":
            groups.append((credential_target("STT", provider_id), refs))

    transforms = _dict(config.get("transforms"))
    llm = _dict(transforms.get("llm"))
    llm_provider = str(llm.get("provider", "none")).strip().lower() or "none"
    if llm and llm_provider not in {"none", "ollama"}:
        groups.append((credential_target("LLM", llm_provider), [(llm, "api_key")]))

    remote = _dict(config.get("remote"))
    if remote:
        groups.append((credential_target("Remote", "control-token"), [(remote, "token")]))
    return groups


def _group_secret(refs: list[tuple[dict[str, Any], str]]) -> str:
    for container, key in refs:
        value = str(container.get(key, "")).strip()
        if value:
            return value
    return ""


def _set_group(refs: list[tuple[dict[str, Any], str]], value: str) -> None:
    for container, key in refs:
        container[key] = value


def hydrate_config_secrets(config: dict[str, Any], *, store: CredentialStore | None = None) -> dict[str, Any]:
    backend = store or credential_store()
    if backend.available:
        for target, refs in _secret_groups(config):
            plaintext = _group_secret(refs)
            vaulted = backend.read(target)
            selected = plaintext or vaulted
            if plaintext:
                backend.write(target, plaintext)
            if selected:
                _set_group(refs, selected)
    config[_HYDRATED_MARKER] = True
    return config


# Targets whose secret could not be stored in this process. Read by Settings so
# a refusal is visible rather than silent -- the field simply going empty with
# no explanation is the second-worst outcome after writing it to disk.
_VAULT_FAILURES: set[str] = set()


def _record_vault_failure(target: str) -> None:
    _VAULT_FAILURES.add(target)


def vault_failures() -> tuple[str, ...]:
    """Targets the credential store refused this session, newest last."""
    return tuple(sorted(_VAULT_FAILURES))


def config_for_persistence(config: dict[str, Any], *, store: CredentialStore | None = None) -> dict[str, Any]:
    persisted = copy.deepcopy(config)
    backend = store or credential_store()
    hydrated = bool(config.get(_HYDRATED_MARKER, False))
    if backend.available:
        for target, refs in _secret_groups(persisted):
            secret = _group_secret(refs)
            if secret:
                # X-202: a REFUSED write used to fall through and leave the
                # secret in the dict, which then went to config.json in
                # plaintext -- while Settings went on saying the key was
                # protected by Windows. The store refuses any secret over 2560
                # bytes, which is not hypothetical: a Google service-account
                # JSON is comfortably larger, and so is any long-lived JWT.
                #
                # A failed write now blanks the field anyway. Losing a key the
                # user can paste again is a smaller harm than silently writing
                # it to a file they were told never holds it, and the failure
                # is recorded rather than swallowed so Settings can say so.
                if backend.write(target, secret):
                    _set_group(refs, "")
                else:
                    _set_group(refs, "")
                    _record_vault_failure(target)
            elif hydrated:
                backend.delete(target)
    persisted.pop(_HYDRATED_MARKER, None)
    return persisted


def credential_storage_status() -> str:
    """What Settings tells the user about where their keys live.

    A refusal has to appear HERE. The whole reason X-202 was safe to fix by
    blanking the field is that the user finds out; blanking silently would
    just replace a leak with a key that vanished for no stated reason.
    """
    description = credential_store().description
    failures = vault_failures()
    if not failures:
        return description
    names = ", ".join(target.rsplit("/", 1)[-1] for target in failures)
    return (
        f"{description} -- but it refused to store {names}. "
        "Those keys were NOT written to disk, and need entering again."
    )


def delete_all_credentials(
    config: dict[str, Any] | None = None,
    *,
    store: CredentialStore | None = None,
    include_license: bool = True,
) -> bool:
    """Erase every secret this app put in the vault.

    `include_license` exists for the in-app reset (X-195). Resetting settings
    must clear provider keys without silently signing a paying customer out;
    only the "account" category is allowed to take the entitlement. The
    uninstaller keeps the default and takes everything.
    """
    backend = store or credential_store()
    if not backend.available:
        return False
    targets = {
        *(credential_target("STT", provider_id) for provider_id in _vaultable_stt_ids()),
        *(credential_target("LLM", provider_id) for provider_id in _vaultable_llm_ids()),
        credential_target("Remote", "control-token"),
    }
    if include_license:
        targets.add(credential_target("License", "entitlement"))
    if isinstance(config, dict):
        targets.update(target for target, _refs in _secret_groups(config))
    deleted_all = True
    for target in targets:
        if not backend.delete(target):
            deleted_all = False
    return deleted_all
