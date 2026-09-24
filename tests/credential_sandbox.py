"""An in-memory vault for the suite, separate for each synthetic data home."""
import os
from pathlib import Path
import sys
import threading

from knight_flow import credentials

class MemoryStore:
    available = True
    description = "Isolated test credential store"

    def __init__(self):
        self.values = {}
        self.lock = threading.RLock()

    def read(self, target):
        with self.lock:
            return self.values.get(target, "")

    def write(self, target, secret):
        with self.lock:
            self.values[target] = secret
        return True

    def delete(self, target):
        with self.lock:
            self.values.pop(target, None)
        return True

_stores = {}
_lock = threading.RLock()

def isolated_store():
    home = str(Path(os.environ["TALK_DAT_HOME"]).absolute())
    with _lock:
        return _stores.setdefault(home, MemoryStore())

def install():
    previous = credentials.credential_store
    credentials.credential_store = isolated_store
    # Direct imports made before tests were loaded must get the same boundary.
    for name in ("knight_flow.licensing",
                 "knight_flow.web_shell.shell_persistence"):
        module = sys.modules.get(name)
        if module is not None and getattr(module, "credential_store", None) is previous:
            module.credential_store = isolated_store
