"""X-542: read the founder's app log over a window with TWO bounds.

The daily issue scan reports what went wrong in his copy of Talk DAT! over
the last ~26 hours, by reading `%APPDATA%\\TalkDat\\talk-dat.log`. That file
contains a deliberate clock-skew fixture left by a 2026-08-10 test whose
lines are dated **2116-12-31 / 2117-01-01** -- 28 of them as of today,
including a WARNING that reads:

    update check failed: ... [SSL: CERTIFICATE_VERIFY_FAILED] certificate
    verify failed: certificate has expired

There is no expired certificate. There never was. But that line has now come
within one step of being reported as a live outage twice, by two different
routes, and the second route is the reason this module exists:

  * **2026-09-08, by string comparison.** `awk '$1>="2026-09-07"'` compares
    the dates as text, and "2116..." sorts above "2026...", so the skew lines
    land in the window. The trap was written down, and the remedy written
    down with it was "filter by real date parsing".
  * **2026-09-13, by date comparison.** That remedy is not sufficient, and
    believing it is worse than not having it -- it retires the suspicion
    while leaving the fault. `datetime(2116, 12, 31) >= now - 26h` is simply
    TRUE. A floor-only window admits exactly the same line for a better
    reason, and today's scan reproduced it: parsed as real datetimes, with a
    lower bound only, the expired-certificate warning came back as an
    in-window finding. Only a ceiling removed it.

So the property is not "parse the dates". It is that a window has two ends.

The second rule here is that a rejected line is REPORTED, not dropped.
`future` keeps every record the ceiling rejected, and `note` names their
dates, because a scan that silently discards the lines it cannot place will
one day discard a real one with them. The dates are enough to recognise a
fixture; the messages stay out of the note so the artifact can never be
quoted back as news.

`scan()` is pure and takes its clock as an argument -- it is what the tests
drive. `main()` does the file reading and owns the exit codes, which follow
X-541's contract: **0 quiet, 1 findings, 2 could not read**, so a caller
treating non-zero as failure can never read "could not check" as "fine".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, OrderedDict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence

# A third state beside True and False, matching `installed_versions.UNKNOWN`.
# Callers must branch on identity: `if window.quiet:` would pass this off as
# a green, which is the failure both sentinels exist to prevent.
CANNOT_READ = "cannot-read"

DEFAULT_HOURS = 26

# A log line written while this scan runs is real, not skew. Anything beyond
# this is a clock that does not belong to today.
CEILING_SLACK = timedelta(minutes=5)

_LINE = re.compile(
    r"^(?P<when>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(?P<ms>\d{3}) "
    r"(?P<level>[A-Z]+) (?:(?P<logger>[\w.]+): )?(?P<message>.*)$"
)

_LOUD_LEVELS = ("ERROR", "CRITICAL", "FATAL")

# Shapes that matter even when the app logged them at INFO.
_CRASH = re.compile(r"traceback|update install failed|crash|unhandled", re.I)
_MANAGED_CLOUD = re.compile(r"managed cloud (blocked|refused|unavailable)", re.I)

# Volatile parts of a message, so "session 4f95ef62" and "session e2c605ab"
# count as one repetition rather than two singletons.
_VOLATILE = re.compile(r"[0-9a-f]{8,}|\d+")


@dataclass(frozen=True)
class Record:
    when: datetime
    level: str
    logger: str
    message: str
    detail: str = ""

    @property
    def shape(self) -> str:
        return _VOLATILE.sub("#", self.message)


@dataclass(frozen=True)
class Finding:
    kind: str
    count: int
    sample: str
    first: datetime


# X-545: a hard crash writes here and NOWHERE the scan was reading.
#
# `faulthandler` dumps to `crash-traceback.log`. The process is already gone,
# so `talk-dat.log` gets no traceback, no ERROR, not a line -- and this module
# reads only `talk-dat.log`. The founder's 2026-09-14 heap corruption reached
# the scan as a single WARNING about recovered AUDIO, which exists only because
# a protected voice session happened to be in flight. A crash a second either
# side of a dictation is a quiet log over a machine that fell over.
#
# The dump has no timestamps of its own. mtime is the only clock and it dates
# the LAST record only; the ones before it are undated and stay that way. Said
# out loud in the finding rather than smoothed over, because a confident date
# on four undated records is worse than no date at all.
_FAULT = re.compile(r"^Windows fatal exception: (?P<fault>.+)$", re.M)
_FRAME = re.compile(r'^  File "(?P<file>[^"]+)", line (?P<line>\d+) in (?P<func>.+)$', re.M)


@dataclass(frozen=True)
class Crash:
    fault: str
    frame: str
    when: datetime
    records: int
    in_window: bool


def read_crash_dump(
    text: str,
    mtime: datetime,
    *,
    now: datetime,
    hours: int = DEFAULT_HOURS,
    slack: timedelta = CEILING_SLACK,
) -> "Crash | None":
    """The last fault in a faulthandler dump, or None if there is no fault in it.

    The LAST one, specifically: the file is append-only across the life of the
    install and mtime belongs to its final record. Reporting the first would
    put today's date on the oldest crash in the file.
    """
    faults = _FAULT.findall(text)
    if not faults:
        return None
    tail = text[text.rfind("Windows fatal exception:"):]
    # The faulting thread is the one marked "Current thread". Some records have
    # no Python frame at all (a fault inside the GC), hence the fallbacks.
    current = tail.rfind("Current thread")
    match = _FRAME.search(tail[current:] if current != -1 else tail) or _FRAME.search(tail)
    frame = (
        f'{match.group("file")}:{match.group("line")} in {match.group("func")}'
        if match
        else "no Python frame"
    )
    return Crash(
        fault=faults[-1].strip(),
        frame=frame,
        when=mtime,
        records=len(faults),
        in_window=(now - timedelta(hours=hours)) <= mtime <= (now + slack),
    )


@dataclass(frozen=True)
class Window:
    records: tuple[Record, ...] = ()
    future: tuple[Record, ...] = ()
    stale: int = 0
    unreadable: int = 0
    findings: tuple[Finding, ...] = ()
    quiet: object = True
    note: str = ""
    floor: datetime | None = None
    ceiling: datetime | None = None


def _attach(records: list[list], text: str) -> None:
    """Continuation lines (a traceback body) belong to the record above."""
    if records:
        records[-1][1].append(text)


def _parse(lines: Iterable[str]) -> tuple[list[Record], int]:
    """Split the log into records, folding unprefixed lines into their owner."""
    building: list[list] = []
    orphans = 0
    for raw in lines:
        text = raw.rstrip("\n")
        match = _LINE.match(text)
        if match:
            try:
                when = datetime.strptime(match.group("when"), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                # A date that is not a date is not a record. It cannot be
                # placed in or out of the window, so it is an orphan.
                orphans += 1
                continue
            building.append([
                Record(
                    when=when,
                    level=match.group("level"),
                    logger=match.group("logger") or "",
                    message=match.group("message"),
                ),
                [],
            ])
        elif text.strip():
            if building:
                _attach(building, text)
            else:
                orphans += 1

    records = []
    for record, detail in building:
        records.append(
            Record(
                when=record.when,
                level=record.level,
                logger=record.logger,
                message=record.message,
                detail="\n".join(detail),
            )
        )
    return records, orphans


def _group(records: Sequence[Record]) -> "OrderedDict[tuple[str, str], list[Record]]":
    groups: OrderedDict[tuple[str, str], list[Record]] = OrderedDict()
    for record in records:
        groups.setdefault((record.level, record.shape), []).append(record)
    return groups


def _findings(records: Sequence[Record]) -> tuple[Finding, ...]:
    """Classify each record group exactly once, loudest first.

    Deliberately one kind per group: a WARNING that also says "update install
    failed" is one finding, not two. Double-reporting the same line is how a
    findings list stops being countable.
    """
    loud: list[Finding] = []
    warned: list[Finding] = []
    quietly_wrong: list[Finding] = []

    for (level, _shape), group in _group(records).items():
        first = group[0]
        count = len(group)
        if level in _LOUD_LEVELS:
            loud.append(Finding("error", count, first.message, first.when))
        elif level == "WARNING":
            kind = "repeated-warning" if count > 2 else "warning"
            warned.append(Finding(kind, count, first.message, first.when))
        else:
            body = f"{first.message}\n{first.detail}"
            if _CRASH.search(body):
                quietly_wrong.append(Finding("crash", count, first.message, first.when))
            elif _MANAGED_CLOUD.search(first.message) and count > 2:
                quietly_wrong.append(
                    Finding("managed-cloud", count, first.message, first.when)
                )

    # Repetition ahead of one-offs within the warnings, so the noisiest thing
    # in the window is the first thing read.
    warned.sort(key=lambda f: (f.kind != "repeated-warning", f.first))
    return tuple([*loud, *warned, *quietly_wrong])


def scan(
    lines: Iterable[str],
    *,
    now: datetime,
    hours: int = DEFAULT_HOURS,
    slack: timedelta = CEILING_SLACK,
) -> Window:
    """Window the log between a floor and a ceiling, and judge what is inside.

    `now` is an argument and not a call to the clock so the tests can pin a
    date the fixture lines sit far outside of.
    """
    floor = now - timedelta(hours=hours)
    ceiling = now + slack

    records, orphans = _parse(lines)
    if not records:
        return Window(
            unreadable=orphans,
            quiet=CANNOT_READ,
            note=(
                "No parseable log record was found, so nothing was checked. "
                "This is not a report that his copy is healthy."
            ),
            floor=floor,
            ceiling=ceiling,
        )

    inside = tuple(r for r in records if floor <= r.when <= ceiling)
    future = tuple(r for r in records if r.when > ceiling)
    stale = sum(1 for r in records if r.when < floor)

    findings = _findings(inside)

    parts = []
    if not inside:
        parts.append(
            f"no activity in the last {hours}h "
            f"({len(records)} record(s) in the file, all outside the window)"
        )
    else:
        parts.append(f"{len(inside)} record(s) in the last {hours}h")
        parts.append("nothing to report" if not findings else f"{len(findings)} finding(s)")
    if future:
        dates = sorted({r.when.strftime("%Y-%m-%d") for r in future})
        # Dates only. The messages are fixture text and must never be
        # quotable out of this note as though they described today.
        parts.append(
            f"{len(future)} line(s) dated in the future were excluded from the "
            f"window ({', '.join(dates)}) -- clock-skew fixture data, not news"
        )
    if orphans:
        parts.append(f"{orphans} unreadable line(s)")

    return Window(
        records=inside,
        future=future,
        stale=stale,
        unreadable=orphans,
        findings=findings,
        quiet=not findings,
        note="; ".join(parts) + ".",
        floor=floor,
        ceiling=ceiling,
    )


def verdict_exit_code(window: Window) -> int:
    """0 quiet, 1 findings, 2 could not read -- X-541's contract."""
    if window.quiet is CANNOT_READ:
        return 2
    return 0 if window.quiet else 1


def default_log_path() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "TalkDat" / "talk-dat.log"


def default_crash_path() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "TalkDat" / "crash-traceback.log"


def fold_in_crash(window: Window, crash: "Crash | None", name: str) -> Window:
    """Add a recent crash dump to the window's findings.

    A dump outside the window is deliberately NOT a finding and NOT silent: it
    goes in the note with its date, the same bargain the excluded future lines
    get. `CANNOT_READ` is never overwritten -- "could not check" outranks
    "found something", or the exit code would call a blind run a seen one.
    """
    if crash is None:
        return window
    stamp = f"{crash.when:%Y-%m-%d %H:%M}"
    undated = (
        f"; the dump carries no timestamps, so this dates the LAST of "
        f"{crash.records} record(s) only"
    )
    if not crash.in_window:
        return replace(
            window,
            note=(window.note + f" {name} exists and was last written {stamp}, "
                  f"outside the window{undated}.").strip(),
        )
    finding = Finding(
        kind="crash-dump",
        count=1,
        sample=f"{crash.fault} at {crash.frame} ({name} written {stamp}{undated})",
        first=crash.when,
    )
    return replace(
        window,
        findings=window.findings + (finding,),
        quiet=window.quiet if window.quiet is CANNOT_READ else False,
    )


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - I/O shell
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", default="", help="log file (default: his TalkDat log)")
    parser.add_argument("--hours", type=int, default=DEFAULT_HOURS)
    parser.add_argument("--crash-path", default="", help="faulthandler dump (default: beside his log)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    path = Path(args.path) if args.path else default_log_path()
    now = datetime.now()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        window = Window(
            quiet=CANNOT_READ,
            note=f"Could not read {path}: {error.__class__.__name__}. Nothing was checked.",
        )
    else:
        window = scan(lines, now=now, hours=args.hours)

    crash_path = Path(args.crash_path) if args.crash_path else default_crash_path()
    try:
        crash = read_crash_dump(
            crash_path.read_text(encoding="utf-8", errors="replace"),
            datetime.fromtimestamp(crash_path.stat().st_mtime),
            now=now,
            hours=args.hours,
        )
    except OSError:
        # No dump is the ordinary case and is not a finding. An unreadable one
        # is not claimed as absent either -- it simply does not fold in.
        crash = None
    window = fold_in_crash(window, crash, crash_path.name)

    if args.json:
        print(json.dumps({
            "quiet": window.quiet if window.quiet is CANNOT_READ else bool(window.quiet),
            "inWindow": len(window.records),
            "excludedFuture": len(window.future),
            "findings": [
                {"kind": f.kind, "count": f.count, "sample": f.sample, "first": f.first.isoformat()}
                for f in window.findings
            ],
            "note": window.note,
        }, indent=2))
    else:
        state = "CANNOT READ" if window.quiet is CANNOT_READ else ("QUIET" if window.quiet else "FINDINGS")
        print(f"{state}: {window.note}")
        for finding in window.findings:
            print(f"  [{finding.kind} x{finding.count}] {finding.first:%Y-%m-%d %H:%M} {finding.sample[:160]}")

    return verdict_exit_code(window)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
