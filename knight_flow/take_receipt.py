"""T7: a take locked to this machine, and a receipt of what actually ran.

Talk DAT already makes the promise globally. `privacy.local_only` (X-465, on by
default) is the one switch the speech route, the formatter resolver and every
door that lets text leave all read, and with the Local route on net_fence.py
refuses every content-carrying connection at the socket boundary (X-338).
Translation runs on this machine or not at all (X-516). Two things were
missing: the promise could not be asked for ONE take by someone who normally
uses their own provider key -- "this one is a medical note" -- without changing
the whole install; and nothing recorded what a take actually used, so the
promise could be trusted but not checked.

A locked take is the same single switch, turned on for that take's config
(`lock_take`), plus the fence held up for the take's lifetime whatever the
global route says (`net_fence.begin_take(locked=True)`). Every resolver then
answers exactly as it does on a local-only install: speech on the local model,
formatting by the local engine or the built-in rules, and a missing local model
refuses the take as it already does (app.py), with the audio kept for recovery,
instead of quietly switching route.

The receipt records, per take, the speech route and model, the formatter route,
the translation route and every outbound connection a content helper asked for,
refused or not. A locked take whose receipt shows remote use would be a bug.

This is evidence of routing. It is not a compliance claim, and nothing here
makes one.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any


def lock_take(config: dict[str, Any]) -> dict[str, Any]:
    """The take's config with local-only on. The stored config is untouched."""
    locked = dict(config)
    privacy = dict(config.get("privacy") or {}) if isinstance(config.get("privacy"), dict) else {}
    privacy["local_only"] = True
    locked["privacy"] = privacy
    locked["_take_locked"] = True
    return locked


@dataclass
class TakeReceipt:
    locked: bool
    speech_route: str = ""
    speech_model: str = ""
    formatter_route: str = ""
    translation_route: str = ""
    remote_attempts: list[dict[str, Any]] = field(default_factory=list)
    stopped: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def remote_used(self) -> list[str]:
        return sorted({str(item.get("host")) for item in self.remote_attempts if not item.get("refused")})

    @property
    def remote_refused(self) -> list[str]:
        return sorted({str(item.get("host")) for item in self.remote_attempts if item.get("refused")})

    def verdict(self) -> str:
        """What this take can honestly say about where it ran."""
        if self.stopped:
            return "stopped"
        if self.remote_used:
            return "used a remote service"
        if self.remote_refused:
            return "stayed on this computer; remote attempts were refused"
        return "stayed on this computer"


def planned_routes(config: dict[str, Any]) -> TakeReceipt:
    """The routes the resolvers choose for this config, before the take runs."""
    from .llm import resolved_llm_provider
    from .stt_registry import provider_settings, resolve_route
    from .translation import auto_translation_enabled

    # provider_settings fills in defaults IN PLACE; a plan must not write the
    # person's stored settings, so it reads a copy.
    scratch = copy.deepcopy(config)
    speech = resolve_route(scratch)
    settings = provider_settings(scratch, speech) if speech else {}
    formatter = resolved_llm_provider(scratch)
    return TakeReceipt(
        locked=bool(config.get("_take_locked")),
        speech_route=speech,
        speech_model=str(settings.get("model") or ""),
        formatter_route=formatter if formatter not in ("", "none") else "rules",
        translation_route="local" if auto_translation_enabled(config) else "off",
    )


def finish_receipt(receipt: TakeReceipt, take_net: Any, *, format_route: str = "", stopped: str = "") -> TakeReceipt:
    """Fill in what happened: the fence's record of connection attempts, the
    formatter that actually produced the text (the rules when the engine was
    not ready), and a stop reason if the take never ran."""
    finished = copy.copy(receipt)
    finished.remote_attempts = [dict(item) for item in getattr(take_net, "attempts", [])]
    if format_route:
        finished.formatter_route = format_route
    finished.stopped = stopped
    return finished
