"""The suite's isolation for the processes the product starts (coordinator,
after full suite r3: a child that runs product code without the test package
has no guard and no audio stand-in, and reading its code is not a check).

A plugin's worker (knight_flow.plugins) is a multiprocessing "spawn" child: a
fresh interpreter that imports its entry point by name. With plugin_host as
that entry point, the worker imports this package first, so the guard and the
audio stand-in are in place before any of the plugin's code runs, whatever
started the suite (a bare `python -m unittest` parent re-imports nothing).
"""
from __future__ import annotations

from knight_flow import plugins
from knight_flow.plugin_worker import main as _plugin_host


def plugin_host(connection, path) -> None:
    """knight_flow.plugin_worker.main, reached through the test package."""
    _plugin_host(connection, path)


def install() -> None:
    plugins._run_host = plugin_host
