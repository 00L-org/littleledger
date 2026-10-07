"""Links: which observations are one booking, and which payment settles which card statement.

Ids: '<source>:<n>' is the n-th booking a parser reads from a file and '<source>:0' the file as a statement;
<source> is the first twelve hex digits of the file's SHA-256, so an id depends on neither name nor amount.

Rules link only what the data proves. LINKS.csv in the archive root records what was decided, one line per
decision: left_id;right_id;kind;basis
  same      left and right are one booking seen in two files
  distinct  left and right are unrelated, although a rule paired them
  settles   payment left settles card statement right ('<source>:0'); left '-': paid from an account not read
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

FIELDS = ["left_id", "right_id", "kind", "basis"]
NO_REF = {"", "NONREF", "NOTPROVIDED"}
WINDOW = 30                     # days after a card statement's end within which its payment is booked
OUTSIDE = "-"                   # left_id of a payment from an account that is not read


def ref(o: dict) -> str:
    r = (o.get("ref") or "").strip()
    return "" if r.upper() in NO_REF else r


def read(root: Path) -> list[dict]:
    """Decisions from LINKS.csv, each with its line number."""
    path = root / "LINKS.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [{**{k: (r.get(k) or "").strip() for k in FIELDS}, "line": n}
                for n, r in enumerate(csv.DictReader(fh, delimiter=";"), start=2)]


def usable(decisions: list[dict], obs: dict, statements: dict):
    """(decisions that fit the data, [(decision, why) for the others]); the others are ignored until fixed.
    obs: observations of files that passed their check, by id; statements: card statements, by id."""
    good, bad = [], []
    for d in decisions:
        a = obs.get(d["left_id"])
        b = statements.get(d["right_id"]) if d["kind"] == "settles" else obs.get(d["right_id"])
        if d["kind"] == "distinct" and b is None:
            b = statements.get(d["right_id"])
        if d["kind"] not in ("same", "distinct", "settles"):
            why = f"unknown kind '{d['kind']}'"
        elif b is None or (a is None and (d["kind"], d["left_id"]) != ("settles", OUTSIDE)):
            why = "unknown id: its file is gone, failed its check, or is read differently since"
        elif d["kind"] == "same" and (a["source"] == b["source"] or a["account"] != b["account"]
                                      or a["amount"] != b["amount"]):
            why = "'same' needs two files of one account and equal amounts"
        elif d["kind"] == "settles" and a is not None and a["account"] == b["account"]:
            why = "a card statement is paid from another account"
        else:
            good.append(d)
            continue
        bad.append((d, why))
    for sid, s in statements.items():                # the payments of a statement add up to its amount due
        paying = [d for d in good if d["kind"] == "settles" and d["right_id"] == sid]
        if paying and all(d["left_id"] != OUTSIDE for d in paying) \
                and sum(obs[d["left_id"]]["amount"] for d in paying) != s["due"]:
            good = [d for d in good if d not in paying]
            bad += [(d, f"the payments of {sid} do not add up to its amount due {s['due']}") for d in paying]
    return good, bad


def groups(obs: list[dict], key):
    """Observations with equal key, grouped so that the n-th of one file meets only the n-th of another:
    the bookings of one file, which its balance check proves distinct, never share a group."""
    out, count = {}, {}
    for o in obs:
        k = key(o)
        if k is not None:
            n = count[k, o["source"]] = count.get((k, o["source"]), 0) + 1
            out.setdefault((k, n), []).append(o)
    return out.values()


def pairs(obs: list[dict]):
    """Observations from different files that a rule relates, as (first, other, kind):
      same       equal bank reference, day and amount
      conflict   equal bank reference, other day or amount
      duplicate  equal day, amount, counterparty and text, where at least one has no reference"""
    order = {o["id"]: i for i, o in enumerate(obs)}
    merged, flagged = set(), set()
    for group in groups(obs, lambda o: (o["account"], ref(o), o["booking_date"], o["amount"]) if ref(o) else None):
        for other in group[1:]:
            merged.update((group[0]["id"], other["id"]))
            yield group[0], other, "same"
    by_ref = {}
    for o in obs:
        if ref(o):
            by_ref.setdefault((o["account"], ref(o)), []).append(o)
    for same_ref in by_ref.values():
        for o in same_ref:
            other = next((g for g in same_ref if g["source"] != o["source"]), None)
            if o["id"] in merged or other is None or frozenset((o["id"], other["id"])) in flagged:
                continue
            flagged.add(frozenset((o["id"], other["id"])))
            first, second = sorted((o, other), key=lambda x: order[x["id"]])
            yield first, second, "conflict"
    for group in groups(obs, lambda o: (o["account"], o["booking_date"], o["amount"],
                                        (o.get("counterparty") or "")[:60], o["text"][:60])):
        for other in group[1:]:
            if not (ref(group[0]) and ref(other)):       # two references speak for themselves
                yield group[0], other, "duplicate"


def merge(obs: list[dict], decisions: list[dict]):
    """(booking id of every observation, open questions [(kind, first, other)], refused decisions [(d, why)]).
    A booking takes the id of its first observation and never holds two observations of one file."""
    order = {o["id"]: i for i, o in enumerate(obs)}
    root = {o["id"]: o["id"] for o in obs}
    sources = {o["id"]: {o["source"]} for o in obs}

    def find(x):
        while root[x] != x:
            root[x] = root[root[x]]
            x = root[x]
        return x

    def join(a, b) -> bool:
        a, b = sorted((find(a), find(b)), key=order.get)
        if a != b:
            if sources[a] & sources[b]:
                return False
            root[b] = a
            sources[a] |= sources[b]
        return True

    verdict = {frozenset((d["left_id"], d["right_id"])): d["kind"]
               for d in decisions if d["kind"] in ("same", "distinct")}
    questions = []
    for first, other, kind in pairs(obs):
        if frozenset((first["id"], other["id"])) in verdict:
            continue                                     # decided in LINKS.csv
        if kind == "same":
            join(first["id"], other["id"])               # a rule group holds one observation per file
        else:
            questions.append((kind, first, other))
    refused = [(d, "would merge two bookings of one file") for d in decisions
               if d["kind"] == "same" and not join(d["left_id"], d["right_id"])]
    return {i: find(i) for i in root}, questions, refused


def settle(bookings: list[dict], statements: dict, owner: dict, decisions: list[dict], booking_of: dict,
           until: dict):
    """({payment booking id: statement id}, open questions, {statement id: note}).
    A payment settles a card statement by decision, or by rule when it is the only booking of exactly the
    amount due, in its currency, on a non-card account of the card's owner, within WINDOW days after the
    statement's end, and the only statement it could pay. A statement with an amount due and no payment is
    a question once an account of its owner is read beyond that window (until: account -> last covered day)."""
    links, outside = {}, set()
    for d in decisions:
        if d["kind"] == "settles":
            if d["left_id"] == OUTSIDE:
                outside.add(d["right_id"])
            else:
                links[booking_of[d["left_id"]]] = d["right_id"]
    unrelated = {frozenset((booking_of.get(d["left_id"], d["left_id"]), booking_of.get(d["right_id"], d["right_id"])))
                 for d in decisions if d["kind"] == "distinct"}
    cards = {s["account"] for s in statements.values()}
    payers = {s["account"]: [a for a, o in owner.items() if o == owner[s["account"]] and a not in cards]
              for s in statements.values()}
    candidates, ends = {}, {}
    for sid, s in statements.items():
        if sid in links.values() or sid in outside or not s["due"] or not s["end"]:
            continue
        ends[sid] = end = date.fromisoformat(s["end"]) + timedelta(days=WINDOW)
        candidates[sid] = [b for b in bookings
                           if b["id"] not in links and b["account"] in payers[s["account"]]
                           and (b["amount"], b["currency"]) == (s["due"], s["currency"])
                           and end - timedelta(days=WINDOW) <= date.fromisoformat(b["booking_date"]) <= end
                           and frozenset((b["id"], sid)) not in unrelated]
    claims = {}
    for found in candidates.values():
        for b in found:
            claims[b["id"]] = claims.get(b["id"], 0) + 1
    questions, notes = [], {}
    for sid, found in candidates.items():
        if len(found) == 1 and claims[found[0]["id"]] == 1:
            links[found[0]["id"]] = sid
        elif found:
            questions += [("settles", statements[sid], b) for b in found]
            notes[sid] = f"{len(found)} possible payments: decide in LINKS.csv"
        elif any(until.get(a) and until[a] >= ends[sid] for a in payers[statements[sid]["account"]]):
            questions.append(("unpaid", statements[sid], None))
            notes[sid] = f"no payment found up to {ends[sid]}: decide in LINKS.csv"
    by_id = {b["id"]: b for b in bookings}
    for sid, s in statements.items():
        paid = [by_id[p] for p, r in links.items() if r == sid]
        if paid:
            notes[sid] = "settled by " + ", ".join(f"{b['account']} {b['booking_date']} ({b['id']})" for b in paid)
        elif sid in outside:
            notes[sid] = "paid from an account that is not read (LINKS.csv)"
        elif not s["due"]:
            notes[sid] = "nothing due"
        elif sid not in notes:
            notes[sid] = "no payment found yet" if s["end"] else "no stated period: link its payment in LINKS.csv"
    return links, questions, notes
