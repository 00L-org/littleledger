"""Transactions: parse the bank files of every account that names a parser in PROFILE.md.

Output
  build/transactions.csv   transactions of all files that passed their check, one schema,
                           sorted by booking date and account
  build/check-report.txt   per source file: OK (balances add up), FAIL (excluded), SKIP (layout not supported)
Overlapping exports contain the same transaction twice; dedupe() keeps one.
"""
from __future__ import annotations

import csv
from pathlib import Path

from lib.accounts import digits, load, problems
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
    """Drop transactions repeated by overlapping exports; return (kept, removed, conflicts).
    Key: the bank reference where one exists; the same reference with another day or amount is
    kept and reported as a conflict. Otherwise account, day, amount, counterparty and text, counted
    within each source file, so identical real payments stay separate."""
    seen, kept, counter, conflicts = {}, [], {}, []
    for r in rows:
        ref = (r.get("ref") or "").strip()
        if ref.upper() not in NO_REF:
            key = ("ref", r["account"], ref)
            if key in seen and seen[key] != (r["booking_date"], str(r["amount"])):
                conflicts.append(r)
                kept.append(r)
                continue
        else:
            sig = (r["account"], r["booking_date"], str(r["amount"]), r.get("counterparty", "")[:60],
                   r["text"][:60], r["source_file"])
            counter[sig] = counter.get(sig, 0) + 1
            key = ("sig", sig[:5], counter[sig])
        if key not in seen:
            seen[key] = (r["booking_date"], str(r["amount"]))
            kept.append(r)
    return kept, len(rows) - len(kept), conflicts


def run(root: Path) -> int:
    accounts = load(root)
    for p in problems(accounts):
        print(p)
    if problems(accounts):
        return 1
    rows, checks = [], []
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
            found, check = parse(f, a["account"], f.relative_to(root).as_posix(), ids)
            if check["ok"]:                  # failed files never reach the transaction table
                rows += found
            checks.append((a["account"], check))
    rows, removed, conflicts = dedupe(rows)
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
    lines += [f"CONFLICT {r['account']} ref {r['ref']}: {r['booking_date']} {r['amount']} in {r['source_file']}"
              for r in conflicts]
    version = (root / "system" / "VERSION").read_text(encoding="utf-8").strip() \
        if (root / "system" / "VERSION").exists() else "?"
    summary = (f"{len(checks)} files: {len(checks) - failed - skipped} ok, {failed} failed and excluded, "
               f"{skipped} skipped (layout not supported); {len(rows)} transactions after removing "
               f"{removed} duplicates from overlapping exports; {len(conflicts)} reference conflicts. "
               f"finance-archive {version}")
    (build / "check-report.txt").write_text("\n".join(lines + ["", summary, ""]), encoding="utf-8")
    print("\n".join(l for l in lines if not l.startswith(("OK", "SKIP"))) + ("\n" if failed or conflicts else "")
          + summary)
    return 1 if failed or conflicts else 0
