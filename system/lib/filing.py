"""Filing: move documents from inbox/ into raw/ with canonical names, deduplicated and indexed.

Layout
  raw/bank/<account>/<kind>/<year>/<date>_<account>_<kind>.<ext>      bank files, recognised by name
  raw/belege/<category>/<year>/<date>_<source>_<description>[_<no>].<ext>   other files, via raw/CATALOG.csv
  raw/<file>                                                          metadata kept by this tool
Documents live only in subfolders of raw/. Nothing is deleted: duplicates and unpacked
archives go to build/discarded/ and are logged in raw/DISCARDED.csv.
"""
from __future__ import annotations

import csv
import hashlib
import re
import shutil
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from lib.accounts import Accounts, load

UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})
CATALOG_FIELDS = ["original", "date", "category", "source", "description", "doc_no", "year"]
INDEX_FIELDS = ["path", "sha256", "bytes", "original", "category", "source", "description", "date"]


def unmangle(s: str) -> str:
    """ZIP member names often arrive as UTF-8 misread as CP437."""
    try:
        return s.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", unmangle(s or "").translate(UMLAUTS))
    s = re.sub(r"[^A-Za-z0-9]+", "-", s.encode("ascii", "ignore").decode()).strip("-").lower()
    return re.sub(r"-{2,}", "-", s)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def documents(raw: Path):
    """All document files in raw/: everything in subfolders except hidden files and README.md notes."""
    return sorted(p for p in raw.rglob("*") if p.is_file() and p.parent != raw
                  and not p.name.startswith(".") and p.name != "README.md")


# ------------------------------------------------------------------ bank files
def camt_info(path: Path):
    """(kind, IBAN, first date, last date) of a camt.052/053 file, or None."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None
    ns = root.tag.split("}")[0].strip("{")
    m = re.search(r"camt\.05([23])", ns)
    if not m:
        return None
    q = {"d": ns}
    iban = root.find(".//d:Acct/d:Id/d:IBAN", q)
    days = sorted(e.text[:10] for e in root.findall(".//d:Ntry/d:BookgDt/d:Dt", q) if e.text)
    frm = root.find(".//d:FrToDt/d:FrDtTm", q)
    to = root.find(".//d:FrToDt/d:ToDtTm", q)
    first = frm.text[:10] if frm is not None else (days[0] if days else None)
    last = to.text[:10] if to is not None else (days[-1] if days else None)
    if iban is None or not first:
        return None
    return f"camt05{m.group(1)}", iban.text, first, last


def plan_bank(path: Path, acc: Accounts):
    """(account, kind, year, base name) for a bank file, or None. Rules are tried in order."""
    name, folder = path.name, path.parent.name

    # Haspa camt.052 "booked" download: folder <from>-<to>-<number>-camt52Booked, one XML per day
    o = re.match(r"(?:unzipped_|entpackt_)?\d{8}-\d{8}-(\d+)-camt5([23])Booked$", folder)
    t = re.match(r"(\d{4})\.(\d{2})\.(\d{2})\.xml$", name)
    if o and t and acc.find(o.group(1)):
        a, kind, day = acc.find(o.group(1)), f"camt05{o.group(2)}", f"{t.group(1)}-{t.group(2)}-{t.group(3)}"
        return a, kind, t.group(1), f"{day}_{a}_{kind}-tag"

    # camt export named <dd_mm_yyyy>-<dd_mm_yyyy>_C52_<IBAN>_EUR[_<part>].xml (Sparkassen, MLP)
    m = re.search(r"_C5([23])_(DE\d{20})_", name)
    z = re.match(r"(\d{2})_(\d{2})_(\d{4})-(\d{2})_(\d{2})_(\d{4})", name)
    if m and z and acc.find(m.group(2)):
        a, kind = acc.find(m.group(2)), f"camt05{m.group(1)}"
        frm, to = f"{z.group(3)}-{z.group(2)}-{z.group(1)}", f"{z.group(6)}-{z.group(5)}-{z.group(4)}"
        base = f"{frm}_bis_{to}_{a}_{kind}"
        part = re.search(r"_(\d{6})\.xml$", name)
        return a, kind, frm[:4], base + (f"_teil-{int(part.group(1))}" if part else "")

    # Haspa statement PDF
    m = re.match(r"Konto_(\d+)-Auszug_(\d{4})_(\d+)\.pdf$", name, re.I)
    if m and acc.find(m.group(1)):
        a = acc.find(m.group(1))
        return a, "kontoauszug", m.group(2), f"{m.group(2)}-{int(m.group(3)):02d}_{a}_kontoauszug"

    # Haspa Mastercard statement PDF: <card>_Abrechnung_vom_<date>_<holder>.pdf
    m = re.match(r"\d{4}\w*?(\d{4})_Abrechnung_vom_(\d{2}_\d{2}_\d{4}|\d{4}-\d{2}-\d{2})_", name, re.I)
    if m and acc.find(m.group(1)):
        a, d = acc.find(m.group(1)), m.group(2)
        day = f"{d[6:10]}-{d[3:5]}-{d[0:2]}" if "_" in d else d
        return a, "abrechnung", day[:4], f"{day}_{a}_abrechnung"

    # Haspa CSV export: <yyyymmdd>-<number>-umsatz[...].csv
    m = re.match(r"(\d{4})(\d{2})(\d{2})-(\d+)-umsatz(.*)\.csv$", name, re.I)
    if m and acc.find(m.group(4)):
        a, day = acc.find(m.group(4)), f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        variant = "camt-csv" if "camt" in m.group(5).lower() else "csv"
        return a, "umsatzexport", m.group(1), f"{day}_{a}_umsatzexport-{variant}"

    # Degussa Bank statement PDF: <no><number>_Kontoauszug_<dd.mm.yyyy>.pdf
    m = re.match(r"(\d)(\d{7})_Kontoauszug_(\d{2})\.(\d{2})\.(\d{4})\.pdf$", name, re.I)
    if m and acc.find(m.group(2)):
        a, day = acc.find(m.group(2)), f"{m.group(5)}-{m.group(4)}-{m.group(3)}"
        return a, "kontoauszug", m.group(5), f"{day}_{a}_kontoauszug-nr-{m.group(1)}_degussa-{m.group(2)}"

    # OLB statement PDF: <x> Kontoauszug_Nr._<no>_<number>_<yyyy-mm-dd>_<x>.pdf
    m = re.match(r"\d+ Kontoauszug_Nr\._(\d+)_(\d{10})_(\d{4})-(\d{2})-(\d{2})_\d+\.pdf$", name, re.I)
    if m and acc.find(m.group(2)):
        a, day = acc.find(m.group(2)), f"{m.group(3)}-{m.group(4)}-{m.group(5)}"
        return a, "kontoauszug", m.group(3), f"{day}_{a}_kontoauszug-nr-{m.group(1)}_olb-{m.group(2)}"

    # OLB camt export without account in the name: Umsaetze_XML-Export_<yyyy-mm-dd>.xml
    m = re.match(r"Ums.{1,3}tze_XML-Export_(\d{4})-(\d{2})-(\d{2})\.xml$", name, re.I)
    info = camt_info(path) if m else None
    if m and info and acc.find(info[1]):
        a, day = acc.find(info[1]), f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        return a, "camt-export", m.group(1), f"{day}_{a}_umsatzexport-camt052"

    # MLP statement PDF: <number>_<year>_Nr.<no>_Kontoauszug_vom_<yyyy.mm.dd>_<x>.pdf
    m = re.match(r"(\d+)_(\d{4})_Nr\.(\d+)_Kontoauszug_vom_(\d{4})\.(\d{2})\.(\d{2})_\d+\.pdf$", name, re.I)
    if m and acc.find(m.group(1)):
        a, day = acc.find(m.group(1)), f"{m.group(4)}-{m.group(5)}-{m.group(6)}"
        return a, "kontoauszug", m.group(2), f"{day}_{a}_kontoauszug-nr-{int(m.group(3)):03d}"

    # MLP credit card statement: X..<last3>_<year>_Kreditkarten-Umsatzaufstellung_vom_<yyyy.mm.dd>_<x>.pdf
    m = re.match(r"X+(\d{3})_(\d{4})_Kreditkarten-Umsatzaufstellung_vom_(\d{4})\.(\d{2})\.(\d{2})_\d+\.pdf$", name, re.I)
    if m and acc.find(m.group(1)):
        a, day = acc.find(m.group(1)), f"{m.group(3)}-{m.group(4)}-{m.group(5)}"
        return a, "umsatzaufstellung", m.group(2), f"{day}_{a}_umsatzaufstellung"

    # MLP CSV export: Umsaetze_<IBAN>_<yyyy.mm.dd>.csv
    m = re.match(r"Umsaetze_(DE\d{20})_(\d{4})[.-](\d{2})[.-](\d{2})\.csv$", name, re.I)
    if m and acc.find(m.group(1)):
        a, day = acc.find(m.group(1)), f"{m.group(2)}-{m.group(3)}-{m.group(4)}"
        return a, "umsatzexport", m.group(2), f"{day}_{a}_umsatzexport-csv"

    # MLP postbox letter: [<number>_<year>_]<title>_vom_<yyyy.mm.dd>_<x>.pdf
    m = re.match(r"(?:(\d+)_(\d{4})_)?(.+?)_vom_(\d{4})\.(\d{2})\.(\d{2})_\d+\.pdf$", name, re.I)
    a = m and (acc.find(m.group(1) or "") or acc.postbox("MLP"))
    if m and a:
        day = f"{m.group(4)}-{m.group(5)}-{m.group(6)}"
        return a, "bankschreiben", m.group(2) or m.group(4), f"{day}_{a}_{slug(m.group(3))}"

    # Older Haspa card statement PDF and card CSV
    m = re.match(r"Abrechnung_\d{4}_(\d{4})_(\d{4})(\d{2})(\d{2})\.pdf$", name, re.I)
    if m and acc.find(m.group(1)):
        a, day = acc.find(m.group(1)), f"{m.group(2)}-{m.group(3)}-{m.group(4)}"
        return a, "abrechnung", m.group(2), f"{day}_{a}_abrechnung"
    m = re.match(r"umsatz-\d{4}\D*(\d{4})-(\d{4})(\d{2})(\d{2})\.csv$", name, re.I)
    if m and acc.find(m.group(1)):
        a, day = acc.find(m.group(1)), f"{m.group(2)}-{m.group(3)}-{m.group(4)}"
        return a, "umsatzexport", m.group(2), f"{day}_{a}_umsatzexport-csv"

    # Any other camt file: account from the IBAN inside, dates from its content
    info = camt_info(path) if path.suffix.lower() == ".xml" else None
    if info and acc.find(info[1]):
        kind, iban, first, last = info
        a = acc.find(iban)
        return a, kind, first[:4], f"{first}_bis_{last}_{a}_{kind}"
    return None


# --------------------------------------------------------------------- catalog
def load_catalog(raw: Path) -> dict:
    path = raw / "CATALOG.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:  # macOS stores names in NFD, the CSV holds NFC
        return {unicodedata.normalize("NFC", r["original"]): r
                for r in csv.DictReader(fh, delimiter=";") if r.get("original")}


def plan_catalog(name: str, catalog: dict):
    """(category, year, base name) for a catalogued file, or None."""
    e = catalog.get(unicodedata.normalize("NFC", name))
    if not e:
        return None
    if e["category"] == "discard":
        return "discard", "", slug(e["description"] or Path(name).stem)
    parts = [e["date"], slug(e["source"]), slug(e["description"])]
    if e.get("doc_no"):
        parts.append(slug(e["doc_no"]))
    year = e.get("year") or (e["date"][:4] if e.get("date") else "ohne-jahr")
    return e["category"], year, "_".join(p for p in parts if p)


# --------------------------------------------------------------------- running
def unzip(inbox: Path, discarded: Path, apply: bool) -> int:
    """Unpack ZIP archives in inbox/ into inbox/unzipped_<name>/; the archive goes to build/discarded/."""
    archives = sorted(p for p in inbox.glob("*") if p.suffix.lower() == ".zip")
    for z in archives:
        target = inbox / f"unzipped_{z.stem}"
        print(f"  unzip {z.name} -> inbox/{target.name}/")
        if apply:
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(z) as zf:
                for info in zf.infolist():
                    if not info.is_dir():
                        (target / Path(unmangle(info.filename)).name).write_bytes(zf.read(info))
            (discarded / "archives").mkdir(parents=True, exist_ok=True)
            shutil.move(str(z), str(discarded / "archives" / z.name))
    return len(archives)


def run(root: Path, apply: bool = False) -> int:
    inbox, raw, discarded = root / "inbox", root / "raw", root / "build" / "discarded"
    acc, catalog = Accounts(load(root)), load_catalog(raw)
    if not inbox.exists():
        print("inbox/ does not exist: nothing to file.")
        return 0
    if unzip(inbox, discarded, apply) and not apply:
        print("  (archives are unpacked with --apply; run again afterwards)\n")
    known = {sha256(p): p.relative_to(root) for p in documents(raw)}
    moves, duplicates, unknown = [], [], []

    for src in sorted(inbox.rglob("*")):
        if not src.is_file() or src.name.startswith("."):
            continue
        ext = {"jpeg": "jpg"}.get(src.suffix.lower().lstrip("."), src.suffix.lower().lstrip("."))
        bank = plan_bank(src, acc)
        if bank:
            account, kind, year, base = bank
            target = raw / "bank" / account / kind / year / f"{base}.{ext}"
            meta = {"category": "bank", "source": account, "description": kind, "doc_no": ""}
        else:
            plan = plan_catalog(src.name, catalog)
            if not plan:
                unknown.append(src.relative_to(root))
                continue
            category, year, base = plan
            e = catalog[unicodedata.normalize("NFC", src.name)]
            if category == "discard":
                target = discarded / f"{base}.{ext}"
            elif category.startswith("bank/"):          # bank letter without a name rule
                target = raw / category / year / f"{base}.{ext}"
            else:
                target = raw / "belege" / category / year / f"{base}.{ext}"
            meta = {"category": category, "source": e["source"], "description": e["description"],
                    "doc_no": e.get("doc_no", "")}
        h = sha256(src)
        if h in known:
            duplicates.append((src, known[h], h))
            continue
        if target.exists() or any(m["to"] == target for m in moves):   # same name, other content
            target = target.with_name(f"{target.stem}_{h[:6]}{target.suffix}")
        known[h] = target.relative_to(root)
        moves.append({"from": src, "to": target, **meta})

    if apply:
        for m in moves:
            if m["to"].exists():
                raise SystemExit(f"STOP: {m['to']} already exists")
            m["to"].parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(m["from"]), str(m["to"]))
        if duplicates:
            (discarded / "duplicates").mkdir(parents=True, exist_ok=True)
            log = raw / "DISCARDED.csv"
            new = not log.exists()
            with log.open("a", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh, delimiter=";")
                if new:
                    w.writerow(["time", "file", "reason", "identical_to", "sha256"])
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                for src, same, h in duplicates:
                    d = discarded / "duplicates" / src.name
                    if d.exists():
                        d = d.with_name(f"{d.stem}_{h[:6]}{d.suffix}")
                    shutil.move(str(src), str(d))
                    w.writerow([now, src.name, "identical to a file in raw/", same, h])
        if moves or duplicates:
            write_index(root, catalog)

    print(f"{'MOVED' if apply else 'WOULD MOVE'}: {len(moves)}")
    for m in moves:
        print(f"  {m['from'].name}\n    -> {m['to'].relative_to(root)}")
    if duplicates:
        print(f"\nDUPLICATES ({len(duplicates)}) -> build/discarded/duplicates/:")
        for src, same, _ in duplicates:
            print(f"  {src.name}  (same as {same})")
    if unknown:
        print(f"\nNO RULE ({len(unknown)}): add a row to raw/CATALOG.csv or the account to PROFILE.md")
        for u in unknown:
            print(f"  {u}")
    return 0


def write_index(root: Path, catalog: dict) -> None:
    """Rebuild raw/INDEX.csv and raw/MANIFEST.sha256 from what is actually in raw/."""
    raw = root / "raw"
    by_base = {}
    for original, e in catalog.items():
        plan = plan_catalog(original, catalog)
        if plan and plan[0] != "discard":
            by_base[plan[2]] = (original, e)
    rows = []
    for p in documents(raw):
        rel = p.relative_to(raw)
        original, e = by_base.get(p.stem, ("", None))
        rows.append([rel.as_posix(), sha256(p), p.stat().st_size, original,
                     e["category"] if e else rel.parts[0], e["source"] if e else "",
                     e["description"] if e else "", e["date"] if e else ""])
    with (raw / "INDEX.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(INDEX_FIELDS)
        w.writerows(rows)
    with (raw / "MANIFEST.sha256").open("w", encoding="utf-8") as fh:
        fh.writelines(f"{r[1]}  {r[0]}\n" for r in rows)
    print(f"\nraw/INDEX.csv and raw/MANIFEST.sha256 rewritten: {len(rows)} documents")


def verify(root: Path) -> int:
    """Compare every document in raw/ with raw/MANIFEST.sha256."""
    raw = root / "raw"
    manifest = raw / "MANIFEST.sha256"
    if not manifest.exists():
        print("raw/MANIFEST.sha256 missing: nothing to verify yet.")
        return 0
    expected = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            h, path = line.split("  ", 1)
            expected[path] = h
    present = {p.relative_to(raw).as_posix(): p for p in documents(raw)}
    missing = sorted(set(expected) - set(present))
    unlisted = sorted(set(present) - set(expected))
    changed = sorted(k for k in set(expected) & set(present) if sha256(present[k]) != expected[k])
    for label, items in (("MISSING", missing), ("CHANGED", changed), ("NOT IN MANIFEST", unlisted)):
        for i in items:
            print(f"{label}: raw/{i}")
    ok = not (missing or changed or unlisted)
    print(f"{len(expected)} documents in manifest, {len(present)} in raw/: "
          + ("all intact." if ok else f"{len(missing)} missing, {len(changed)} changed, {len(unlisted)} not listed."))
    return 0 if ok else 1
