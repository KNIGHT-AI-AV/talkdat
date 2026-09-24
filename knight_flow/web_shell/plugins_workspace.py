"""Explicit plugin maintenance, with all imports and reloads off the UI."""

from __future__ import annotations
from knight_flow import plugins


class PluginsWorkspace:
    def __init__(self, config, busy, open_path):
        self.config, self.busy, self.open_path = config, busy, open_path

    def handle(self, payload):
        if type(payload) is not dict or set(payload) != {"command"}:
            raise ValueError("Choose a plugin action.")
        command = payload["command"]
        if command == "status":
            return plugins.snapshot(self.config)
        if command == "reload":
            if self.busy():
                raise ValueError(
                    "Finish the current recording before reloading plugins."
                )
            if not plugins.plugins_enabled(self.config):
                raise ValueError(
                    "Enable plugins and save that choice before loading them."
                )
            plugins.request_reload(self.config)
            return plugins.snapshot(self.config)
        if command == "folder":
            self.open_path(plugins.plugins_dir())
            return {"message": "Opened your local plugins folder."}
        raise ValueError("That plugin action is unavailable.")
