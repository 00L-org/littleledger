"""Parsers: raw bank files -> bookings plus a check of the file against its own balances.

Each parser returns (bookings, check).
  booking: account, booking_date, value_date, amount (Decimal, sign from the holder's view),
           currency, counterparty, text, type, ref, source_type, source_file
  check:   file, n, ok (True passed, False failed, None layout not supported), balances, and
           periods: (first day, last day) for each statement in the file, as the statement itself states
                    it; never taken from its bookings; empty when the file states none
           due:     card statements only: the amount charged to the account that pays the card
A file whose check fails must not feed any analysis: either the parser or the file is wrong.
"""
from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path


def dec(s: str) -> Decimal:
    return Decimal(s.replace(".", "").replace(",", "."))


def iso(d: str) -> str:
    day, month, year = d.split(".")
    return f"{'20' + year if len(year) == 2 else year}-{month}-{day}"


def after(day: str) -> str:
    """The day after an ISO date. A balance as of a day closes that day, so the next statement starts later."""
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def pdftext(pdf: Path) -> str:
    return subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                          capture_output=True, text=True, check=True).stdout


def row(account, booking, value, amount, counterparty, text, typ, source_type, source, ref=""):
    return {"account": account, "booking_date": booking, "value_date": value, "amount": amount,
            "currency": "EUR", "counterparty": counterparty, "text": text, "type": typ,
            "ref": ref, "source_type": source_type, "source_file": source}


# -------------------------------------------------------- Haspa statement PDF
# Opening balance; closing balance of the booking list (appendices after it are not bookings).
RE_OPEN = re.compile(r"Kontostand am (\d{2}\.\d{2}\.\d{4}), Auszug Nr\.\s*\d+\s+(-?[\d.]*\d,\d{2})")
RE_CLOSE = re.compile(r"Kontostand am (\d{2}\.\d{2}\.\d{4}) um \d{2}:\d{2} Uhr\s+(-?[\d.]*\d,\d{2})")
# Booking lines are indented by two characters on page 1 only: allow up to four spaces.
RE_BOOKING = re.compile(r"^ {0,4}(\d{2}\.\d{2}\.\d{4})\s+(\S.*?)\s{2,}(-?[\d.]*\d,\d{2})\s*$")


def parse_haspa_text(txt: str, account: str, source: str):
    """Haspa layouts: 2018 'Buchungs- / Tag der', 2019-2021 'Datum Wert Erl.', from 2022 'Datum Erl. Betrag'.
    Only the layout from 2022 is parsed; older ones are reported as not supported."""
    name = Path(source).name
    opening, closing = RE_OPEN.search(txt), RE_CLOSE.search(txt)
    periods = [(after(iso(opening.group(1))), iso(closing.group(1)))] if opening and closing else []
    if re.search(r"Buchungs-\s+Tag der", txt) or re.search(r"Datum\s+Wert\s+Erl", txt):
        return [], {"file": name, "n": 0, "ok": None, "periods": periods, "note": "layout before 2022, no parser yet"}
    rows, current = [], None
    for line in (raw.rstrip() for raw in txt.splitlines()):
        if RE_CLOSE.search(line):
            break
        if not line.strip() or "Übertrag:" in line:
            current = None
            continue
        m = RE_BOOKING.match(line)
        if m:
            current = row(account, iso(m.group(1)), None, dec(m.group(3)), "", "", m.group(2).strip(),
                          "pdf-kontoauszug", source)
            rows.append(current)
        elif current is not None and len(line) - len(line.lstrip()) >= 6:
            current["text"] = (current["text"] + " " + line.strip()).strip()
        else:
            current = None
    total = sum((r["amount"] for r in rows), Decimal(0))
    check = {"file": name, "n": len(rows), "periods": periods}
    if opening and closing:
        start, end = dec(opening.group(2)), dec(closing.group(2))
        check.update(opening=start, closing=end, sum=total, difference=end - (start + total),
                     ok=start + total == end)
    else:
        check.update(ok=False, note="opening or closing balance not found")
    return rows, check


def parse_haspa_statement(pdf: Path, account: str, source: str, ids=()):
    return parse_haspa_text(pdftext(pdf), account, source)


# --------------------------------------------------- Haspa Mastercard statement
RE_CARD = re.compile(r"^(\d{2}\.\d{2}\.\d{2})\s+(\d{2}\.\d{2}\.\d{2})\s+(\S.*?)\s{2,}([\d.]*\d,\d{2})\s*([+-])\s*$")
RE_CARD_FEE = re.compile(r"^\s{6,}(\S.*?)\s{2,}([\d.]*\d,\d{2})\s*([+-])\s*$")
RE_CARD_BALANCE = re.compile(r"Neuer Saldo\s+([\d.]*\d,\d{2})\s*([+-])")
RE_CARD_PERIOD = re.compile(r"Ihre Abrechnung vom (\d{2}\.\d{2}\.\d{4}) bis (\d{2}\.\d{2}\.\d{4})")


def parse_haspa_card_text(txt: str, account: str, source: str):
    rows, last = [], None
    for line in (raw.rstrip() for raw in txt.splitlines()):
        if "Neuer Saldo" in line or "Zwischensumme" in line or "Übertrag von Seite" in line:
            last = None                      # page totals repeat bookings; they are not bookings
            continue
        m = RE_CARD.match(line)
        if m:
            sign = Decimal(-1) if m.group(5) == "-" else Decimal(1)
            merchant = re.sub(r"\s{2,}.*$", "", m.group(3)).strip()
            last = row(account, iso(m.group(2)), iso(m.group(1)), dec(m.group(4)) * sign, merchant, "",
                       "Kartenumsatz", "pdf-kkabrechnung", source)
            rows.append(last)
            continue
        f = RE_CARD_FEE.match(line)
        if f and last is not None:           # e.g. foreign transaction fee
            sign = Decimal(-1) if f.group(3) == "-" else Decimal(1)
            rows.append({**last, "amount": dec(f.group(2)) * sign, "type": f.group(1).strip(),
                         "text": "Nebenkosten zu: " + last["counterparty"]})
            continue
        if last is not None and line.strip() and len(line) - len(line.lstrip()) >= 6:
            if not re.search(r"Seite \d+ von|Hamburger Sparkasse|Mastercard-Nummer|Karteninhaber|Abrechnung", line):
                last["counterparty"] = (last["counterparty"] + " " + line.strip()).strip()
    total = sum((r["amount"] for r in rows), Decimal(0))
    balance, period = RE_CARD_BALANCE.search(txt), RE_CARD_PERIOD.search(txt)
    check = {"file": Path(source).name, "n": len(rows), "sum": total,
             "periods": [(after(iso(period.group(1))), iso(period.group(2)))] if period else []}
    if balance:                          # the new balance is charged to the paying account in full
        b = dec(balance.group(1)) * (Decimal(-1) if balance.group(2) == "-" else Decimal(1))
        check.update(closing=b, due=b, difference=b - total, ok=b == total)
    else:
        check.update(ok=False, note="'Neuer Saldo' not found")
    return rows, check


def parse_haspa_card(pdf: Path, account: str, source: str, ids=()):
    return parse_haspa_card_text(pdftext(pdf), account, source)


# ----------------------------------------------------------------- camt.052/053
ITEM_AMOUNTS = ("d:Amt", "d:AmtDtls/d:TxAmt/d:Amt", "d:AmtDtls/d:InstdAmt/d:Amt")


def parse_camt(xml: Path, account: str, source: str, ids=()):
    """Every report in the file must belong to the account (its IBAN among ids) and balance."""
    root = ET.parse(xml).getroot()
    q = {"d": root.tag.split("}")[0].strip("{")}
    reports = root.findall(".//d:Rpt", q) or root.findall(".//d:Stmt", q)
    rows, checks = [], []
    for report in reports:
        found, check = camt_report(report, q, account, source)
        iban = report.find("d:Acct/d:Id/d:IBAN", q)
        number = re.sub(r"\D", "", iban.text if iban is not None and iban.text else "")
        if ids and not (number and any(i.endswith(number) for i in ids)):
            check.update(ok=False, note=f"IBAN {iban.text if iban is not None else '?'} is not this account's")
        rows += found
        checks.append(check)
    if not checks:
        return [], {"file": xml.name, "n": 0, "ok": False, "periods": [], "note": "no camt report found"}
    if len(checks) == 1:
        return rows, {**checks[0], "file": xml.name}
    failed = [c for c in checks if not c["ok"]]
    return rows, {"file": xml.name, "n": len(rows), "ok": not failed,
                  "periods": [p for c in checks for p in c["periods"]],
                  "note": f"{len(checks)} reports" + (f", {len(failed)} failed: {failed[0].get('note', 'balances')}"
                                                      if failed else "")}


def camt_report(report, q, account: str, source: str):
    balances, dates = {}, {}
    for b in report.findall("d:Bal", q):
        code, amount = b.find(".//d:Cd", q).text, Decimal(b.find("d:Amt", q).text)
        balances[code] = amount if b.find("d:CdtDbtInd", q).text == "CRDT" else -amount
        day = b.find("d:Dt/d:Dt", q) if b.find("d:Dt/d:Dt", q) is not None else b.find("d:Dt/d:DtTm", q)
        if day is not None and day.text:
            dates[code] = day.text[:10]
    rows = []
    for e in report.findall("d:Ntry", q):
        value, code = e.find(".//d:ValDt/d:Dt", q), e.find(".//d:Prtry/d:Cd", q)
        for amount, item, scope, note in camt_items(e, q):
            ref = scope.find(".//d:AcctSvcrRef", q)
            if ref is None and scope is not e:
                ref = e.find("d:AcctSvcrRef", q)
            text = note + " ".join(u.text for u in scope.findall(".//d:Ustrd", q) if u.text)
            rows.append({**row(account, e.find(".//d:BookgDt/d:Dt", q).text[:10],
                               value.text[:10] if value is not None else None, amount, party(item, amount, q), text,
                               code.text if code is not None else "", "camt", source,
                               ref.text if ref is not None and ref.text else ""),
                         "currency": e.find("d:Amt", q).get("Ccy", "EUR")})
    total = sum((r["amount"] for r in rows), Decimal(0))
    start = balances.get("OPBD", balances.get("PRCD", Decimal(0)))
    end = balances.get("CLBD")
    span = (report.find("d:FrToDt/d:FrDtTm", q), report.find("d:FrToDt/d:ToDtTm", q))
    if None not in span:                                    # the period the report states
        period = (span[0].text[:10], span[1].text[:10])
    else:                                                   # else its opening (or last closing) and closing balance
        first = dates.get("OPBD") or (after(dates["PRCD"]) if "PRCD" in dates else None)
        period = (first, dates["CLBD"]) if first and "CLBD" in dates else None
    return rows, {"file": "", "n": len(rows), "opening": start, "closing": end, "sum": total,
                  "difference": end - (start + total) if end is not None else None,
                  "ok": end is not None and start + total == end, "periods": [period] if period else []}


def camt_items(e, q):
    """(amount, item, scope, note) for each booking of an entry: item names the counterparty, scope holds
    text and reference. A batch entry is split only where every item states an amount and the amounts add
    up to the entry; otherwise it stays one booking, marked as not itemized."""
    debit = e.find("d:CdtDbtInd", q).text == "DBIT"
    amount = Decimal(e.find("d:Amt", q).text) * (-1 if debit else 1)
    items = e.findall(".//d:TxDtls", q)
    if len(items) < 2:
        return [(amount, items[0] if items else None, e, "")]
    parts = []
    for t in items:
        found = [x for x in (t.find(p, q) for p in ITEM_AMOUNTS) if x is not None]
        if not found:
            break
        ind = t.find("d:CdtDbtInd", q)
        parts.append(Decimal(found[0].text) * (-1 if (ind.text == "DBIT" if ind is not None else debit) else 1))
    if len(parts) == len(items) and sum(parts) == amount:
        return [(p, t, t, "") for p, t in zip(parts, items)]
    return [(amount, None, e, f"batch of {len(items)}, not itemized: ")]


def party(item, amount, q) -> str:
    """The other party of a booking: the creditor of a debit, the debtor of a credit."""
    if item is None:
        return ""
    side = "Cdtr" if amount < 0 else "Dbtr"
    nm = item.find(f".//d:RltdPties/d:{side}/d:Pty/d:Nm", q)
    if nm is None:
        nm = item.find(f".//d:RltdPties/d:{side}/d:Nm", q)
    if nm is None:
        nm = item.find(".//d:Nm", q)
    return nm.text if nm is not None and nm.text else ""
