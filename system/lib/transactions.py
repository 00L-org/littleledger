"""Transactions: parse the bank files of every account that names a parser in PROFILE.md.

Output
  build/transactions.csv   all transactions in one schema, sorted by booking date and account
  build/check-report.txt   per source file: OK (balances add up), FAIL, or SKIP (layout not supported)
Overlapping exports contain the same transaction twice; dedupe() keeps one.
"""
from __future__ import annotations

import csv
from pathlib import Path

from lib.accounts import load
from lib.parsers import parse_camt, parse_haspa_card, parse_haspa_statement

# parser name in PROFILE.md -> (files below raw/bank/<account>/, function)
PARSERS = {
    "camt": ("**/*.xml", parse_camt),
    "haspa-pdf": ("kontoauszug/**/*.pdf", parse_haspa_statement),
    "haspa-card-pdf": ("abrechnung/**/*.pdf", parse_haspa_card),
}
FIELDS = ["account", "booking_date", "value_date", "amount", "currency", "counterparty",
          "text", "type", "ref", "source_type", "source_file"]
NO_REF = {"", "NONREF", "NOTPROVIDED"}


def dedupe(rows: list[dict]):
    """Drop transactions repeated by overlapping exports.
    Key: the bank reference where one exists. Otherwise account, day, amount and text plus a
    counter within the source file, so three identical real payments on one day stay three."""
    seen, kept, counter = set(), [], {}
    for r in rows:
        ref = (r.get("ref") or "").strip()
        if ref.upper() not in NO_REF:
            key = ("ref", r["account"], ref)
        else:
            sig = (r["account"], r["booking_date"], str(r["amount"]), r["text"][:60], r["source_file"])
            counter[sig] = counter.get(sig, 0) + 1
            key = ("sig", sig[:4], counter[sig])
        if key not in seen:
            seen.add(key)
            kept.append(r)
    return kept, len(rows) - len(kept)


def run(root: Path) -> int:
    rows, checks = [], []
    for a in sorted(load(root), key=lambda a: a["account"]):
        name = a.get("parser", "")
        if not name:
            continue
        if name not in PARSERS:
            print(f"unknown parser '{name}' for {a['account']} (known: {', '.join(PARSERS)})")
            continue
        pattern, parse = PARSERS[name]
        for f in sorted((root / "raw" / "bank" / a["account"]).glob(pattern)):
            found, check = parse(f, a["account"], f.relative_to(root).as_posix())
            rows += found
            checks.append((a["account"], check))
    rows, removed = dedupe(rows)
    rows.sort(key=lambda r: (r["booking_date"], r["account"]))

    build = root / "build"
    build.mkdir(exist_ok=True)
    with (build / "transactions.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, FIELDS, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow({k: "" if r.get(k) is None else r[k] for k in FIELDS})

    lines, failed, skipped = [], 0, 0
    for account, c in checks:
        mark = "OK  " if c["ok"] else ("SKIP" if c["ok"] is None else "FAIL")
        failed += c["ok"] is False
        skipped += c["ok"] is None
        extra = f"  difference={c['difference']}" if c.get("difference") else ""
        extra += f"  ({c['note']})" if c.get("note") else ""
        lines.append(f"{mark} {account:24} {c['file']:58} n={c['n']:4}{extra}")
    summary = (f"{len(checks)} files: {len(checks) - failed - skipped} ok, {failed} failed, "
               f"{skipped} skipped (layout not supported); {len(rows)} transactions after removing "
               f"{removed} duplicates from overlapping exports.")
    (build / "check-report.txt").write_text("\n".join(lines + ["", summary, ""]), encoding="utf-8")
    print("\n".join(l for l in lines if not l.startswith(("OK", "SKIP"))) + ("\n" if failed else "") + summary)
    return 1 if failed else 0
