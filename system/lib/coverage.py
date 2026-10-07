"""Coverage: the days for which the archive holds every statement of an account.

A statement covers the period it states (system/lib/parsers.py), and only if its file passed the check.
An account's gaps are the days from its 'complete from' date in PROFILE.md, or else its first covered day,
up to its last covered day that no such statement covers. Later days are not gaps: they are not exported yet.
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from lib.accounts import load, problems, valid_date

FIELDS = ["account", "from", "to", "check", "source_file"]
DAY = timedelta(days=1)


def gaps(periods, start: date | None = None):
    """(last covered day, [(first day, last day) of each gap]) for ISO (from, to) periods; (None, []) if none."""
    spans = sorted((date.fromisoformat(a), date.fromisoformat(b)) for a, b in periods)
    if not spans:
        return None, []
    cursor, holes = start or spans[0][0], []
    for a, b in spans:
        if a > cursor:
            holes.append((cursor, a - DAY))
        cursor = max(cursor, b + DAY)
    return max(b for _, b in spans), holes


def summary(accounts: list[dict], rows: list[dict]) -> dict:
    """{account: (last covered day, gaps)} for every account with a parser; rows as in build/coverage.csv."""
    out = {}
    for a in accounts:
        if a.get("parser"):
            start = (a.get("complete from") or "").strip()
            out[a["account"]] = gaps([(r["from"], r["to"]) for r in rows
                                      if r["account"] == a["account"] and r["check"] == "OK" and r["from"]],
                                     date.fromisoformat(start) if start and valid_date(start) else None)
    return out


def lines(cover: dict) -> list[str]:
    """One line per account: covered until when, and its first gaps."""
    out = []
    for account, (last, holes) in cover.items():
        if last is None:
            out.append(f"{account}: no statement covers a period yet")
            continue
        shown = ", ".join(f"{a}…{b}" if a != b else str(a) for a, b in holes[:3])
        shown += ", …" if len(holes) > 3 else ""
        out.append(f"{account}: until {last}" + (f"; {len(holes)} gap(s): {shown}" if holes else ""))
    return out


def status(root: Path) -> list[str]:
    """Coverage lines for `status`, read from build/coverage.csv."""
    path, manifest = root / "build" / "coverage.csv", root / "raw" / "MANIFEST.sha256"
    if not path.exists():
        return ["Coverage: unknown -> run `python3 system/archive.py transactions`"]
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    stale = manifest.exists() and manifest.stat().st_mtime > path.stat().st_mtime
    accounts = load(root)
    return ["Coverage" + (" (older than the last filing -> run `transactions`)" if stale else "") + ":"] \
        + ["  " + line for line in lines(summary(accounts, rows)) + problems(accounts)]
