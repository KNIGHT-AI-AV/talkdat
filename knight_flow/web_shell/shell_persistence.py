"""Keep credential writes and the atomic settings file consistent on failure."""
from knight_flow.config import _SAVE_LOCK, save_config
from knight_flow.credentials import credential_store, _secret_groups, _group_secret


class _CredentialTransaction:
    def __init__(self, backend):
        self.backend = backend
        self.available = backend.available
        self.before = {}

    def read(self, target):
        return self.backend.read(target)

    def write(self, target, secret):
        old = self.backend.read(target)
        if old == secret:
            return True
        self.before.setdefault(target, old)
        if not self.backend.write(target, secret) or self.backend.read(target) != secret:
            raise ValueError('Protected storage could not save the provider key. Your changes were not saved.')
        return True

    def delete(self, target):
        old = self.backend.read(target)
        if not old:
            return True
        self.before.setdefault(target, old)
        if not self.backend.delete(target) or self.backend.read(target):
            raise ValueError('Protected storage could not remove the provider key. Your changes were not saved.')
        return True

    def rollback(self):
        success = True
        for target, previous in reversed(list(self.before.items())):
            try:
                if self.backend.read(target) != previous:
                    if previous:
                        self.backend.write(target, previous)
                    else:
                        self.backend.delete(target)
                success = self.backend.read(target) == previous and success
            except Exception:
                success = False
        return success


def save_settings_config(config):
    # All existing config saves use this same reentrant lock, including their
    # credential phase. A background save cannot interleave with rollback.
    with _SAVE_LOCK:
        transaction = _CredentialTransaction(credential_store())
        if not transaction.available and any(_group_secret(refs) for _,refs in _secret_groups(config)):
            raise ValueError('Protected key storage is unavailable. Your changes were not saved.')
        try:
            save_config(config, credential_backend=transaction)
        except BaseException:
            if not transaction.rollback():
                raise ValueError('The save failed and a provider key could not be restored. Re-enter that key before using the provider.') from None
            raise
