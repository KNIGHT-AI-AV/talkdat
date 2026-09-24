"""Private-pipe host for trusted local text extensions. This is not a sandbox."""

from __future__ import annotations
import json, os, sys, types
from pathlib import Path

MAX_MESSAGE = 1_048_576
MAX_TEXT = 200_000
MAX_HOOKS = 128


class PluginAPI:
    def __init__(self):
        self.transforms = {}
        self.text_filters = []

    def add_transform(self, transform_id, fn):
        clean = transform_id.strip().lower() if type(transform_id) is str else ""
        if clean and len(clean) <= 80 and callable(fn):
            if clean not in self.transforms and len(self.transforms) >= MAX_HOOKS:
                raise ValueError("Too many plugin transforms")
            self.transforms[clean] = fn

    def add_text_filter(self, fn):
        if callable(fn):
            if len(self.text_filters) >= MAX_HOOKS:
                raise ValueError("Too many plugin filters")
            self.text_filters.append(fn)


def main(connection, path):
    path = Path(path)
    # Plugin print() and accidental logging must never become protocol replies.
    sink = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = sink
    sys.stderr = sink

    def reply(value):
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(raw) > MAX_MESSAGE:
            raw = b'{"ok":false,"error":"OutputTooLarge"}'
        connection.send_bytes(raw)

    try:
        if not path.is_file() or path.stat().st_size > 524288:
            raise ValueError("Unsupported plugin file")
        source = path.read_bytes()
        if len(source) > 524288:
            raise ValueError("Plugin changed during read")
        module = types.ModuleType("talkdat_plugin_" + path.stem)
        module.__file__ = str(path)
        sys.modules[module.__name__] = module
        exec(compile(source, str(path), "exec"), module.__dict__)
        api = PluginAPI()
        register = getattr(module, "register", None)
        if callable(register):
            register(api)
        reply(
            {
                "ok": True,
                "transforms": list(api.transforms),
                "filters": len(api.text_filters),
            }
        )
    except BaseException as error:
        reply({"ok": False, "error": type(error).__name__})
        return
    while True:
        try:
            raw = connection.recv_bytes(MAX_MESSAGE)
        except (OSError, EOFError):
            return
        try:
            request = json.loads(raw)
            text = request["text"]
            config = request["config"]
            if (
                type(text) is not str
                or len(text) > MAX_TEXT
                or type(config) is not dict
            ):
                raise ValueError("Invalid input")
            if request["op"] == "transform":
                fn = api.transforms.get(request["key"])
            elif request["op"] == "filter":
                fn = api.text_filters[int(request["key"])]
            else:
                raise ValueError("Unknown operation")
            if not callable(fn):
                raise ValueError("Unknown hook")
            result = fn(text, config)
            if type(result) is not str or not result.strip() or len(result) > MAX_TEXT:
                reply({"ok": False, "error": "InvalidOutput"})
                continue
            reply({"ok": True, "text": result})
        except BaseException as error:
            reply({"ok": False, "error": type(error).__name__})
