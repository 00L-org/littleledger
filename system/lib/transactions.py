"""Transactions: read the bank files of every account that names a parser in PROFILE.md.

Output in build/
  observations.csv   every booking read, with its id (system/lib/links.py) and its file's check
  transactions.csv   one row per booking from the files that passed their check
  coverage.csv       the period each statement states, with its file's check
  check-report.txt   per file OK, FAIL (left out) or SKIP (layout not supported); open questions; coverage
"""
from __future__ import annotations

import csv
import hashlib
from decimal import Decimal
from pathlib import Path

from lib import coverage, links
from lib.accounts import digits, load, problems
from lib.parsers import parse_camt, parse_haspa_card, parse_haspa_statement

# parser name in PROFILE.md -> (files below raw/bank/<account>/, function)
PARSERS = {
    "camt": ("**/*.xml", parse_camt),
    "haspa-pdf": ("kontoauszug/**/*.pdf", parse_haspa_statement),
    "haspa-card-pdf": ("abrechnung/**/*.pdf", parse_haspa_card),
}
BOOKING = ["account", "booking_date", "value_date", "amount", "currency", "counterparty", "text", "type", "ref",
           "source_type", "source_file"]
OBSERVATIONS = ["id", "check"] + BOOKING
TRANSACTIONS = ["id"] + BOOKING + ["merged", "settles", "open"]


def read(root: Path, accounts: list[dict]):
    """Parse every file: (observations, [(account, mark, check, source)], coverage rows, card statements)."""
    observations, checks, periods, statements, seen = [], [], [], {}, {}
    for a in sorted(accounts, key=lambda a: a["account"]):
        name = a.get("parser", "")
        if not name:
            continue
        if name not in PARSERS:
            print(f"unknown parser '{name}' for {a['account']} (known: {', '.join(PARSERS)})")
            continue
        pattern, parse = PARSERS[name]
        ids = [digits(i) for i in a.get("id", "").split(",") if digits(i)]
        for f in sorted((root / "raw" / "bank" / a["account"]).glob(pattern)):
            source, rel = hashlib.sha256(f.read_bytes()).hexdigest()[:12], f.relative_to(root).as_posix()
            if source in seen:                       # an identical copy adds no evidence
                same = {"file": f.name, "n": 0, "note": f"same content as {seen[source]}"}
                checks.append((a["account"], "SKIP", same, source))
                continue
            seen[source] = rel
            try:
                found, check = parse(f, a["account"], rel, ids)
            except FileNotFoundError:                # the PDF tool is missing (REFERENCE.md › Troubleshooting)
                found, check = [], {"file": f.name, "n": 0, "ok": None, "note": "pdftotext missing"}
            except Exception as e:                   # an unreadable file fails; the others are read on
                found, check = [], {"file": f.name, "n": 0, "ok": False, "note": f"unreadable: {e}"}
            mark = "OK" if check["ok"] else ("SKIP" if check["ok"] is None else "FAIL")
            observations += [{"id": f"{source}:{n}", "check": mark, "source": source, **r}
                             for n, r in enumerate(found, 1)]
            periods += [dict(zip(coverage.FIELDS, (a["account"], p[0], p[1], mark, rel)))
                        for p in check.get("periods") or [("", "")]]
            if check["ok"] and check.get("due") is not None:
                statements[f"{source}:0"] = {"id": f"{source}:0", "account": a["account"], "due": check["due"],
                                             "currency": "EUR", "source": source, "source_file": rel,
                                             "end": check["periods"][-1][1] if check.get("periods") else ""}
            checks.append((a["account"], mark, check, source))
    return observations, checks, periods, statements


def write(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fields, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: "" if r.get(k) is None else r[k] for k in fields})


def run(root: Path) -> int:
    accounts = load(root)
    for p in problems(accounts):
        print(p)
    if problems(accounts):
        return 1
    observations, checks, periods, statements = read(root, accounts)
    passed = [o for o in observations if o["check"] == "OK"]      # failed files never reach the transactions
    decisions, invalid = links.usable(links.read(root), {o["id"]: o for o in passed}, statements)
    booking_of, questions, refused = links.merge(passed, decisions)
    invalid += refused
    bookings = [o for o in passed if booking_of[o["id"]] == o["id"]]
    cover = coverage.summary(accounts, periods)
    owners = {a["account"]: a.get("owner", "").lower() for a in accounts}
    settled, more, notes = links.settle(bookings, statements, owners, decisions, booking_of,
                                        {account: last for account, (last, _) in cover.items()})
    questions += more

    merged, unsure = {}, {}
    for o in passed:
        if booking_of[o["id"]] != o["id"]:
            merged.setdefault(booking_of[o["id"]], []).append(o["id"])
    for kind, first, other in questions:
        if kind == "unpaid":                         # its purchases may count a second time as the payment
            for b in bookings:
                if b["source"] == first["source"]:
                    unsure.setdefault(b["id"], []).append(f"payment of {first['id']} not found")
            continue
        unsure.setdefault(other["id"], []).append({"duplicate": f"duplicate of {first['id']}?",
                                                   "conflict": f"conflict with {first['id']}",
                                                   "settles": f"settles {first['id']}?"}[kind])
    rows = [{**o, "merged": " ".join(merged.get(o["id"], [])), "settles": settled.get(o["id"], ""),
             "open": "; ".join(unsure.get(o["id"], []))} for o in bookings]
    rows.sort(key=lambda r: (r["booking_date"], r["account"]))

    build = root / "build"
    build.mkdir(exist_ok=True)
    write(build / "observations.csv", OBSERVATIONS, observations)
    write(build / "transactions.csv", TRANSACTIONS, rows)
    write(build / "coverage.csv", coverage.FIELDS, periods)

    lines, failed, skipped = [], 0, 0
    for account, mark, c, source in checks:
        failed += mark == "FAIL"
        skipped += mark == "SKIP"
        extra = f"  difference={c['difference']}" if c.get("difference") else ""
        extra += f"  ({c['note']})" if c.get("note") else ""
        extra += f"  {notes[source + ':0']}" if source + ":0" in notes else ""
        lines.append(f"{mark:4} {account:24} {c['file']:58} n={c['n']:4}{extra}")
    for kind, first, other in questions:
        if kind == "unpaid":
            lines.append(f"OPEN {first['account']} card statement {first['id']} ({first['source_file']}): "
                         f"{first['due']} due, {notes[first['id']]}")
            continue
        what = {"duplicate": "perhaps the same booking as", "conflict": "same bank reference as",
                "settles": "perhaps the payment of card statement"}[kind]
        lines.append(f"OPEN {other['account']} {other['booking_date']} {other['amount']} {other['id']} "
                     f"({other['source_file']}): {what} {first['id']} ({first['source_file']})")
    lines += [f"INVALID LINKS.csv line {d['line']}: {why}" for d, why in invalid]
    lines += ["", "Coverage (statements that passed their check):"] + ["  " + line for line in coverage.lines(cover)]

    affected = sum((abs(r["amount"]) for r in rows if r["open"]), Decimal(0))
    version = (root / "system" / "VERSION").read_text(encoding="utf-8").strip() \
        if (root / "system" / "VERSION").exists() else "?"
    paid = set(settled.values()) | {d["right_id"] for d in decisions if d["left_id"] == links.OUTSIDE}
    summary = (f"{len(checks)} files: {len(checks) - failed - skipped} ok, {failed} failed and left out, "
               f"{skipped} skipped; {len(rows)} transactions from {len(passed)} bookings read, "
               f"{len(passed) - len(rows)} seen twice and merged; "
               f"{len(paid & set(statements))} of {len(statements)} card statements settled; "
               f"{len(questions)} open question(s), {affected} provisional; {len(invalid)} invalid link(s); "
               f"{sum(len(h) for _, h in cover.values())} coverage gap(s). littleledger {version}")
    (build / "check-report.txt").write_text("\n".join(lines + ["", summary, ""]), encoding="utf-8")
    print("\n".join(line for line in lines if not line.startswith(("OK", "SKIP"))) + "\n" + summary
          + ("\nDecide open questions in LINKS.csv (system/REFERENCE.md › Transactions)." if questions else ""))
    return 1 if failed or questions or invalid else 0
