"""T3: a project's words stay in that project.

One global dictionary serves everyone badly the moment a person works on two
things at once. The film has a character called Shawn; the client's lead is
Sean; a third project spells it Shaun. All three sound the same, and the
vocabulary matcher -- correctly -- refuses to guess between two terms on one
sound key, so a global dictionary holding all three corrects NONE of them.
Holding only one of them corrects the other two projects wrongly, every time.

So words can belong to a project. A project is chosen by the person (one
active project, or a default per app through its profile); a take uses the
global words plus the active project's, and nothing else. Where a project word
and a global word answer to the same sound with different spellings, that is a
COLLISION: the project's spelling wins for the take, the global one is left
out of that take only, and the collision is reported so the active glossary
can show it. A project may instead keep the global spelling for a term
(`prefer_global`). Switching projects changes the next take and nothing else:
no project's word can leak into another's, because no take ever holds two.

Storage (config["dictionary"], additive; older releases ignore it):
    "projects": [{"id", "name", "words": [...], "terms": [...],
                  "replacements": [...], "prefer_global": [...]}],
    "active_project": "<id>" or "".
A profile may name a default: profiles[i]["project"] = "<id>".

Pure functions; the Settings page and the take's config assembly call them.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


@dataclass(frozen=True)
class Collision:
    sound: str
    project_spelling: str
    global_spelling: str
    winner: str  # "project" or "global"


def _dictionary(config: dict[str, Any]) -> dict[str, Any]:
    dictionary = config.get("dictionary") if isinstance(config, dict) else None
    return dictionary if isinstance(dictionary, dict) else {}


def projects(config: dict[str, Any]) -> list[dict[str, Any]]:
    """The stored projects that are well formed, in their stored order."""
    found, seen = [], set()
    for entry in _dictionary(config).get("projects") or []:
        if not isinstance(entry, dict):
            continue
        project_id = str(entry.get("id") or "")
        if not _ID_RE.match(project_id) or project_id in seen:
            continue
        seen.add(project_id)
        found.append(entry)
    return found


def project_by_id(config: dict[str, Any], project_id: str) -> dict[str, Any] | None:
    for entry in projects(config):
        if entry["id"] == project_id:
            return entry
    return None


def active_project(config: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The person's explicit choice first; otherwise the app profile's default."""
    chosen = str(_dictionary(config).get("active_project") or "")
    if chosen:
        return project_by_id(config, chosen)
    default = str((profile or {}).get("project") or "") if isinstance(profile, dict) else ""
    return project_by_id(config, default) if default else None


def _entries(holder: dict[str, Any]) -> list[Any]:
    return list(holder.get("words") or []) + list(holder.get("terms") or [])


def _spelling(entry: Any) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        return str(entry.get("text") or entry.get("word") or "").strip()
    return ""


def _keys(entry: Any) -> tuple[str, ...]:
    from .vocabulary import parse_terms

    terms = parse_terms([entry])
    return terms[0].keys() if terms else ()


def scoped_dictionary(config: dict[str, Any], project: dict[str, Any] | None) -> tuple[dict[str, Any], list[Collision]]:
    """The dictionary one take uses: global words plus the active project's,
    with every same-sound, different-spelling pair resolved and reported."""
    dictionary = copy.deepcopy(_dictionary(config))
    dictionary.pop("projects", None)
    if not project:
        return dictionary, []
    prefer_global = {str(text).casefold() for text in project.get("prefer_global") or []}
    project_entries = _entries(project)
    project_keys: dict[str, str] = {}
    for entry in project_entries:
        for key in _keys(entry):
            project_keys.setdefault(key, _spelling(entry))
    collisions: list[Collision] = []
    kept_global: dict[str, list[Any]] = {"words": [], "terms": []}
    dropped_project: set[str] = set()
    for field_name in ("words", "terms"):
        for entry in dictionary.get(field_name) or []:
            spelling = _spelling(entry)
            clash = next((key for key in _keys(entry) if key in project_keys), None)
            if clash is None:
                kept_global[field_name].append(entry)
                continue
            if project_keys[clash].casefold() == spelling.casefold():
                continue  # the same word in both; the project's copy is the one used
            if spelling.casefold() in prefer_global or project_keys[clash].casefold() in prefer_global:
                collisions.append(Collision(clash, project_keys[clash], spelling, "global"))
                kept_global[field_name].append(entry)
                dropped_project.add(project_keys[clash].casefold())
            else:
                collisions.append(Collision(clash, project_keys[clash], spelling, "project"))
    project_words = [entry for entry in project.get("words") or [] if _spelling(entry).casefold() not in dropped_project]
    project_terms = [entry for entry in project.get("terms") or [] if _spelling(entry).casefold() not in dropped_project]
    dictionary["words"] = project_words + kept_global["words"]
    dictionary["terms"] = project_terms + kept_global["terms"]
    replacements = list(project.get("replacements") or [])
    overridden = {str(item.get("from", "")).casefold() for item in replacements if isinstance(item, dict)}
    replacements += [item for item in dictionary.get("replacements") or []
                     if not (isinstance(item, dict) and str(item.get("from", "")).casefold() in overridden)]
    dictionary["replacements"] = replacements
    return dictionary, collisions


def apply_word_scope(config: dict[str, Any], project: dict[str, Any] | None) -> dict[str, Any]:
    """A config copy for one take, its dictionary scoped to ``project``."""
    if not project:
        return config
    scoped, collisions = scoped_dictionary(config, project)
    merged = dict(config)
    merged["dictionary"] = scoped
    merged["_word_scope"] = {"project": project["id"], "name": str(project.get("name") or project["id"]),
                             "collisions": [collision.__dict__ for collision in collisions]}
    return merged


def glossary(config: dict[str, Any], project: dict[str, Any] | None) -> list[dict[str, str]]:
    """The active glossary as a person reads it: every spelling a take will use,
    where it comes from, and any collision it won or lost."""
    scoped, collisions = scoped_dictionary(config, project)
    project_spellings = {_spelling(entry).casefold() for entry in _entries(project or {})}
    lost = {collision.global_spelling.casefold(): collision for collision in collisions if collision.winner == "project"}
    rows = []
    for entry in _entries(scoped):
        spelling = _spelling(entry)
        if not spelling:
            continue
        source = "project" if spelling.casefold() in project_spellings else "global"
        rows.append({"text": spelling, "source": source, "note": ""})
    for collision in lost.values():
        rows.append({"text": collision.global_spelling, "source": "global",
                     "note": f"not used here: {collision.project_spelling} wins in this project"})
    for collision in collisions:
        if collision.winner == "global":
            rows.append({"text": collision.project_spelling, "source": "project",
                         "note": f"not used here: kept {collision.global_spelling}"})
    return rows


def new_project(config: dict[str, Any], name: str) -> dict[str, Any]:
    """Add an empty project with an id made from its name; returns it."""
    base = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")[:40] or "project"
    taken = {entry["id"] for entry in projects(config)}
    project_id, number = base, 2
    while project_id in taken:
        project_id, number = f"{base}-{number}", number + 1
    project = {"id": project_id, "name": str(name or "").strip() or project_id, "words": [], "terms": [],
               "replacements": [], "prefer_global": []}
    config.setdefault("dictionary", {}).setdefault("projects", []).append(project)
    return project
