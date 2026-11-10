"""The suite's isolation for the processes the product starts (coordinator,
after full suite r3: a child that runs product code without the test package
has no guard and no audio stand-in, and reading its code is not a check).

A plugin's worker (knight_flow.plugins) is a multiprocessing "spawn" child: a
fresh interpreter that imports its entry point by name. With plugin_host as
that entry point, the worker imports this package first, so the guard and the
audio stand-in are in place before any of the plugin's code runs, whatever
started the suite (a bare `python -m unittest` parent re-imports nothing).

2026-10-25: that makes the suite's worker slower to start than the product's.
Measured on the PC, interpreter start plus import, warm and cold: the product's
worker 0.15 s and 1.2 s, this one 0.5 s and 1.8 s, against the product's load
budget of 1.0 s per plugin and 2.0 s in all. Under load the suite's workers
missed that budget and their loads never registered, so every full-suite run of
0.4.175 logged plugin-host FAILs, a different test each time. The suite gives
its own workers room; the tests that measure the load budget itself take the
product's values back with product_budget().
"""
from __future__ import annotations

import contextlib

from knight_flow import plugins
from knight_flow.plugin_worker import main as _plugin_host

PRODUCT_LOAD_SECONDS = plugins.LOAD_SECONDS
PRODUCT_TOTAL_LOAD_SECONDS = plugins.TOTAL_LOAD_SECONDS
SUITE_LOAD_SECONDS = 15.0
SUITE_TOTAL_LOAD_SECONDS = 60.0


def plugin_host(connection, path) -> None:
    """knight_flow.plugin_worker.main, reached through the test package."""
    _plugin_host(connection, path)


@contextlib.contextmanager
def product_budget():
    """The product's own load budget, for the tests that measure that budget."""
    saved = plugins.LOAD_SECONDS, plugins.TOTAL_LOAD_SECONDS
    plugins.LOAD_SECONDS, plugins.TOTAL_LOAD_SECONDS = PRODUCT_LOAD_SECONDS, PRODUCT_TOTAL_LOAD_SECONDS
    try:
        yield
    finally:
        plugins.LOAD_SECONDS, plugins.TOTAL_LOAD_SECONDS = saved


def install() -> None:
    plugins._run_host = plugin_host
    plugins.LOAD_SECONDS = SUITE_LOAD_SECONDS
    plugins.TOTAL_LOAD_SECONDS = SUITE_TOTAL_LOAD_SECONDS
