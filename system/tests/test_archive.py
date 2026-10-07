"""Self-test with synthetic data only. Run: python3 -m unittest discover -s system/tests"""
import contextlib
import csv
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

SYSTEM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SYSTEM))

from lib import filing, links, session, transactions  # noqa: E402
from lib.accounts import Accounts, load  # noqa: E402
from lib.parsers import parse_camt, parse_haspa_card_text, parse_haspa_text  # noqa: E402

PROFILE = """# Profile

## Owner
- Name: Erika Mustermann
- Language: German
- Style: short bullet points

## Accounts
| account | bank | kind | id | owner | parser | complete from | note |
|---|---|---|---|---|---|---|---|
| `haspa-giro-7890` | Haspa | giro | DE02 2005 0550 1234 5678 90 | self | haspa-pdf | | |
| haspa-mastercard-1111 | Haspa | mastercard | 5232 **** **** 1111 | self | haspa-card-pdf | | |
| mlp-giro-0001 | MLP | giro | DE12672300004000000001 | self | camt | | |
| mlp-card-777 | MLP | card | …777 | self | | | |
| mlp-postbox | MLP | postbox | | self | | | letters |
| test-giro-3000 | Testbank | giro | DE89370400440532013000 | Max Mustermann | camt | | |

## Rules
"""

NS = "urn:iso:std:iso:20022:tech:xsd:camt.052.001.08"


def camt_xml(iban, entries, opening, closing, frm="2025-01-02", to="2025-01-31", span=True, extra=""):
    """entries: (amount, CRDT|DBIT, day, ref or None, counterparty, text); extra: further <Ntry> elements.
    span=False leaves out FrToDt, so only the balance dates state the period."""
    def bal(code, amount, day):
        cd = "CRDT" if amount >= 0 else "DBIT"
        return (f"<Bal><Tp><CdOrPrtry><Cd>{code}</Cd></CdOrPrtry></Tp><Amt Ccy=\"EUR\">{abs(amount):.2f}</Amt>"
                f"<CdtDbtInd>{cd}</CdtDbtInd><Dt><Dt>{day}</Dt></Dt></Bal>")
    body = ""
    for amount, cd, day, ref, name, text in entries:
        debtor, creditor = ("Erika Mustermann", name) if cd == "DBIT" else (name, "Erika Mustermann")
        body += (f"<Ntry><Amt Ccy=\"EUR\">{amount:.2f}</Amt><CdtDbtInd>{cd}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>"
                 f"<BookgDt><Dt>{day}</Dt></BookgDt><ValDt><Dt>{day}</Dt></ValDt>"
                 + (f"<AcctSvcrRef>{ref}</AcctSvcrRef>" if ref is not None else "")
                 + f"<NtryDtls><TxDtls><RltdPties><Dbtr><Pty><Nm>{debtor}</Nm></Pty></Dbtr>"
                 f"<Cdtr><Pty><Nm>{creditor}</Nm></Pty></Cdtr></RltdPties>"
                 f"<RmtInf><Ustrd>{text}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>")
    return (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Document xmlns=\"{NS}\"><BkToCstmrAcctRpt>"
            f"<GrpHdr><MsgId>1</MsgId></GrpHdr><Rpt><Id>1</Id>"
            + (f"<FrToDt><FrDtTm>{frm}T00:00:00</FrDtTm><ToDtTm>{to}T23:59:59</ToDtTm></FrToDt>" if span else "")
            + f"<Acct><Id><IBAN>{iban}</IBAN></Id></Acct>{bal('OPBD', opening, frm)}{bal('CLBD', closing, to)}"
            f"{body}{extra}"
            f"</Rpt></BkToCstmrAcctRpt></Document>")


def two_reports(iban_a, iban_b):
    """camt.052 with two balanced reports: +10 on iban_a, +20 on iban_b."""
    one = camt_xml(iban_a, [(10, "CRDT", "2025-01-03", "A1", "X", "a")], 0, 10)
    two = camt_xml(iban_b, [(20, "CRDT", "2025-01-03", "B1", "Y", "b")], 0, 20)
    rpt = lambda doc: doc[doc.index("<Rpt>"):doc.index("</Rpt>") + 6]
    return one.replace(rpt(one), rpt(one) + rpt(two))


def quiet(fn, *args, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = fn(*args, **kwargs)
    return result, out.getvalue()


class Archive(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "PROFILE.md").write_text(PROFILE, encoding="utf-8")
        for d in ("inbox", "raw", "build"):
            (self.root / d).mkdir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def put(self, rel, content):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode() if isinstance(content, str) else content)
        return p


class TestAccounts(Archive):
    def test_table_and_lookup(self):
        acc = Accounts(load(self.root))
        self.assertEqual(len(acc.rows), 6)
        self.assertEqual(acc.find("1234567890"), "haspa-giro-7890")        # backticks stripped, IBAN suffix
        self.assertEqual(acc.find("1111"), "haspa-mastercard-1111")        # masked card number
        self.assertEqual(acc.find("777"), "mlp-card-777")
        self.assertIsNone(acc.find("0"))                                    # ambiguous
        self.assertIsNone(acc.find("9999999999"))                           # unknown
        self.assertEqual(acc.postbox("MLP"), "mlp-postbox")


class TestBankNames(Archive):
    def plan(self, name, folder="inbox"):
        return filing.plan_bank(self.root / folder / name, Accounts(load(self.root)))

    def test_known_names(self):
        cases = {
            "Konto_1234567890-Auszug_2024_3.pdf":
                ("haspa-giro-7890", "kontoauszug", "2024", "2024-03_haspa-giro-7890_kontoauszug"),
            "5232xxxxxxxx1111_Abrechnung_vom_04_09_2024_Mustermann_Erika.PDF":
                ("haspa-mastercard-1111", "abrechnung", "2024", "2024-09-04_haspa-mastercard-1111_abrechnung"),
            "5232xxxxxxxx1111_Abrechnung_vom_2025-04-03_Mustermann_Erika.PDF":
                ("haspa-mastercard-1111", "abrechnung", "2025", "2025-04-03_haspa-mastercard-1111_abrechnung"),
            "20260901-1234567890-umsatz-camt52v8.CSV":
                ("haspa-giro-7890", "umsatzexport", "2026", "2026-09-01_haspa-giro-7890_umsatzexport-camt-csv"),
            "01_01_2025-01_01_2026_C52_DE12672300004000000001_EUR_000002.xml":
                ("mlp-giro-0001", "camt052", "2025", "2025-01-01_bis_2026-01-01_mlp-giro-0001_camt052_teil-2"),
            "4000000001_2023_Nr.7_Kontoauszug_vom_2023.07.31_20260904111115.pdf":
                ("mlp-giro-0001", "kontoauszug", "2023", "2023-07-31_mlp-giro-0001_kontoauszug-nr-007"),
            "XXXXXXXXXXXX777_2024_Kreditkarten-Umsatzaufstellung_vom_2024.05.02_123.pdf":
                ("mlp-card-777", "umsatzaufstellung", "2024", "2024-05-02_mlp-card-777_umsatzaufstellung"),
            "Umsaetze_DE12672300004000000001_2025.09.04.csv":
                ("mlp-giro-0001", "umsatzexport", "2025", "2025-09-04_mlp-giro-0001_umsatzexport-csv"),
            "Kontoinformation nach §505 Absatz 1 BGB_vom_2023.03.31_20260904111114.pdf":
                ("mlp-postbox", "bankschreiben", "2023", "2023-03-31_mlp-postbox_kontoinformation-nach-505-absatz-1-bgb"),
        }
        for name, expected in cases.items():
            self.assertEqual(self.plan(name), expected, name)

    def test_daily_camt_folder_and_unknown(self):
        self.assertEqual(self.plan("2026.01.15.xml", "inbox/unzipped_20260101-20260131-1234567890-camt52Booked"),
                         ("haspa-giro-7890", "camt052", "2026", "2026-01-15_haspa-giro-7890_camt052-tag"))
        self.assertIsNone(self.plan("Konto_9999999999-Auszug_2024_1.pdf"))
        self.assertIsNone(self.plan("scan_0001.pdf"))

    def test_camt_recognised_by_content(self):
        self.put("inbox/export.xml", camt_xml("DE89370400440532013000", [], 0, 0))
        self.assertEqual(self.plan("export.xml"),
                         ("test-giro-3000", "camt052", "2025", "2025-01-02_bis_2025-01-31_test-giro-3000_camt052"))


class TestFilingRun(Archive):
    def test_file_index_duplicates_verify(self):
        self.put("inbox/Konto_1234567890-Auszug_2024_3.pdf", "statement")
        self.put("inbox/IMG_0001.jpg", "invoice photo")
        self.put("inbox/copy_of_statement.pdf", "statement")                 # same content as above
        self.put("raw/CATALOG.csv", "original;date;category;source;description;doc_no;year\n"
                                    "IMG_0001.jpg;2024-05-06;eingangsrechnung;Müller GmbH;Reparatur Heizung;RE-17;\n"
                                    "copy_of_statement.pdf;2024-03-31;eingangsrechnung;x;y;;\n")
        code, out = quiet(filing.run, self.root, apply=True)
        self.assertEqual(code, 0, out)
        statement = self.root / "raw/bank/haspa-giro-7890/kontoauszug/2024/2024-03_haspa-giro-7890_kontoauszug.pdf"
        invoice = self.root / "raw/belege/eingangsrechnung/2024/2024-05-06_mueller-gmbh_reparatur-heizung_re-17.jpg"
        self.assertTrue(statement.exists() and invoice.exists(), out)
        self.assertTrue((self.root / "build/discarded/duplicates/copy_of_statement.pdf").exists())
        self.assertIn("identical to a file in raw/", (self.root / "raw/DISCARDED.csv").read_text())
        index = (self.root / "raw/INDEX.csv").read_text()
        self.assertIn("IMG_0001.jpg", index)
        self.assertEqual(len((self.root / "raw/MANIFEST.sha256").read_text().splitlines()), 2)
        self.assertEqual(quiet(filing.verify, self.root)[0], 0)
        statement.write_text("tampered")
        self.assertEqual(quiet(filing.verify, self.root)[0], 1)

    def test_unknown_files_stay(self):
        self.put("inbox/unknown.pdf", "x")
        code, out = quiet(filing.run, self.root, apply=True)
        self.assertTrue((self.root / "inbox/unknown.pdf").exists())
        self.assertIn("NO RULE (1)", out)


class TestParsers(Archive):
    def test_camt_balances_and_counterparty(self):
        f = self.put("raw/x.xml", camt_xml("DE89370400440532013000", [
            (50, "CRDT", "2025-01-03", "R1", "Arbeitgeber AG", "Gehalt"),
            (20, "DBIT", "2025-01-04", "R2", "Stadtwerke", "Abschlag"),
        ], 100, 130))
        rows, check = parse_camt(f, "test-giro-3000", "raw/x.xml")
        self.assertTrue(check["ok"], check)
        self.assertEqual([r["amount"] for r in rows], [Decimal("50.00"), Decimal("-20.00")])
        self.assertEqual([r["counterparty"] for r in rows], ["Arbeitgeber AG", "Stadtwerke"])
        rows, check = parse_camt(self.put("raw/y.xml", camt_xml("DE89370400440532013000", [], 100, 99)), "a", "y")
        self.assertFalse(check["ok"])

    def test_haspa_statement_text(self):
        txt = ("Kontostand am 31.12.2023, Auszug Nr. 12          1.000,00\n"
               "  02.01.2024 Lastschrift                         -50,00\n"
               "          Stadtwerke Abschlag Januar\n"
               "  15.01.2024 Gutschrift                          200,00\n"
               "Kontostand am 31.01.2024 um 20:15 Uhr            1.150,00\n"
               "  31.01.2024 Anlage Entgelt                      -9,99\n")
        rows, check = parse_haspa_text(txt, "haspa-giro-7890", "raw/a.pdf")
        self.assertTrue(check["ok"], check)
        self.assertEqual(check["periods"], [("2024-01-01", "2024-01-31")])  # after the opening balance's day
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["text"], "Stadtwerke Abschlag Januar")
        rows, check = parse_haspa_text("Datum   Wert   Erläuterung", "a", "raw/old.pdf")
        self.assertIsNone(check["ok"])

    def test_haspa_card_text(self):
        txt = ("03.01.24  04.01.24  ANTHROPIC SAN FRANCISCO        21,42 -\n"
               "                    Währungsumrechnung 1,75%        0,37 -\n"
               "Neuer Saldo                                       21,79 -\n")
        rows, check = parse_haspa_card_text(txt, "haspa-mastercard-1111", "raw/c.pdf")
        self.assertTrue(check["ok"], check)
        self.assertEqual([r["type"] for r in rows], ["Kartenumsatz", "Währungsumrechnung 1,75%"])
        self.assertEqual(check["periods"], [])                               # no stated period: coverage unknown
        rows, check = parse_haspa_card_text(STATEMENT, "haspa-mastercard-1111", "raw/c.pdf")
        self.assertEqual((check["periods"], check["due"]), ([("2025-02-06", "2025-03-05")], Decimal("-21.79")))


GIRO, CARD = "DE12672300004000000001", "raw/bank/haspa-mastercard-1111/abrechnung/2025"
STATEMENT = ("Ihre Abrechnung vom 05.02.2025 bis 05.03.2025\n"
             "10.02.25  11.02.25  ANTHROPIC SAN FRANCISCO        21,42 -\n"
             "                    Währungsumrechnung 1,75%        0,37 -\n"
             "Neuer Saldo                                       21,79 -\n")


class Books(Archive):
    """Runs `transactions` on synthetic files; card statements are read from text instead of PDF."""

    def setUp(self):
        super().setUp()
        self.parsers = dict(transactions.PARSERS)
        transactions.PARSERS["haspa-card-pdf"] = ("abrechnung/**/*.txt", lambda f, account, source, ids:
                                                  parse_haspa_card_text(f.read_text(), account, source))

    def tearDown(self):
        transactions.PARSERS.clear()
        transactions.PARSERS.update(self.parsers)
        super().tearDown()

    def camt(self, name, entries, opening, closing, frm="2025-01-02", to="2025-01-31", **kw):
        return self.put(f"raw/bank/mlp-giro-0001/camt052/2025/{name}.xml",
                        camt_xml(GIRO, entries, opening, closing, frm, to, **kw))

    def books(self):
        code, out = quiet(transactions.run, self.root)
        read = lambda name: list(csv.DictReader((self.root / "build" / name).read_text(encoding="utf-8").splitlines(),
                                                delimiter=";"))
        return code, out, read("transactions.csv"), read("observations.csv")

    def decide(self, *lines):
        self.put("LINKS.csv", "left_id;right_id;kind;basis\n" + "".join(f"{line};test\n" for line in lines))


class TestObservations(Books):
    def test_rules(self):
        obs = lambda ref, source, text="t", amount="10": {
            "id": f"{source}:{text}", "account": "a", "booking_date": "2025-01-02", "amount": Decimal(amount),
            "counterparty": "", "text": text, "ref": ref, "source": source}
        rows = [obs("R1", "f1"), obs("R1", "f2"),                           # overlap with reference: same
                obs("NONREF", "f1", "rent"), obs("NONREF", "f1", "fee"),    # one file: never related
                obs("", "f1", "x"), obs("", "f2", "x"),                     # no reference: a question
                obs("R9", "f1", "y"), obs("R9", "f2", "y", "11")]           # same reference, other amount
        self.assertEqual(sorted((a["id"], b["id"], k) for a, b, k in links.pairs(rows)),
                         [("f1:t", "f2:t", "same"), ("f1:x", "f2:x", "duplicate"), ("f1:y", "f2:y", "conflict")])

    def test_references_pair_by_day_and_amount(self):
        obs = lambda source, ref, amount, text: {"id": f"{source}:{amount}", "account": "a", "booking_date": "2025-01-02",
                                                 "amount": Decimal(amount), "counterparty": "", "text": text,
                                                 "ref": ref, "source": source}
        rows = [obs("f1", "B1", "-10", "x"), obs("f1", "B1", "-20", "y"),          # a reference used twice
                obs("f2", "B1", "-20", "y"), obs("f2", "B1", "-10", "x"),          # in another order
                obs("f3", "", "-10", "x")]                                         # the same without reference
        self.assertEqual(sorted((a["id"], b["id"], k) for a, b, k in links.pairs(rows)),
                         [("f1:-10", "f2:-10", "same"), ("f1:-10", "f3:-10", "duplicate"),
                          ("f1:-20", "f2:-20", "same")])

    def test_bakery_and_bookshop_stay_apart(self):
        self.camt("a", [(5, "DBIT", "2025-01-03", None, "BAKERY", "card payment")], 5, 0)
        self.camt("b", [(5, "DBIT", "2025-01-03", None, "BOOKSHOP", "card payment")], 5, 0)
        code, out, rows, _ = self.books()
        self.assertEqual((code, len(rows), [r["open"] for r in rows]), (0, 2, ["", ""]), out)

    def test_one_file_lists_each_booking_once(self):
        self.camt("a", [(5, "DBIT", "2025-01-03", None, "BAKERY", "coffee")] * 2, 10, 0)
        code, out, rows, _ = self.books()
        self.assertEqual((code, len(rows), [r["open"] for r in rows]), (0, 2, ["", ""]), out)

    def test_bank_reference_merges_and_keeps_both_sources(self):
        jan = self.camt("jan", [(7, "CRDT", "2025-01-10", "R7", "X", "t")], 0, 7)
        jan2 = self.camt("jan-again", [(7, "CRDT", "2025-01-10", "R7", "X", "t")], 0, 7, "2025-01-05")
        code, out, rows, obs = self.books()
        self.assertEqual((code, len(rows), len(obs)), (0, 1, 2), out)
        sources = {o["id"]: o["source_file"] for o in obs}
        self.assertEqual({sources[rows[0]["id"]], sources[rows[0]["merged"]]},
                         {f.relative_to(self.root).as_posix() for f in (jan, jan2)})

    def test_repeat_without_reference_waits_for_a_decision(self):
        self.camt("a", [(30, "DBIT", "2025-01-03", None, "SHOP", "t")], 30, 0)
        self.camt("b", [(30, "DBIT", "2025-01-03", None, "SHOP", "t")], 30, 0, "2025-01-03")
        code, out, rows, obs = self.books()
        self.assertEqual((code, len(rows)), (1, 2), out)                     # kept twice, marked, provisional
        self.assertIn(f"duplicate of {obs[0]['id']}?", rows[1]["open"])
        self.assertIn("1 open question(s), 30.00 provisional", out)
        self.decide(f"{obs[0]['id']};{obs[1]['id']};same")
        code, out, rows, _ = self.books()
        self.assertEqual((code, len(rows), rows[0]["merged"], rows[0]["open"]), (0, 1, obs[1]["id"], ""), out)
        self.decide(f"{obs[0]['id']};{obs[1]['id']};distinct")
        code, out, rows, _ = self.books()
        self.assertEqual((code, len(rows), rows[1]["open"]), (0, 2, ""), out)

    def test_decisions_never_merge_one_file(self):
        self.camt("a", [(10, "DBIT", "2025-01-03", None, "BAKERY", "t"), (10, "DBIT", "2025-01-03", None, "BOOKSHOP", "t")],
                  20, 0)
        self.camt("b", [(10, "DBIT", "2025-01-03", None, "BAKERY", "t")], 10, 0)
        _, _, _, obs = self.books()
        a1, a2, b1 = (o["id"] for o in obs)
        self.decide(f"{a1};{b1};same", f"{a2};{b1};same")                    # the second is a mistake
        code, out, rows, _ = self.books()
        self.assertEqual(sum(Decimal(r["amount"]) for r in rows), Decimal("-20"), out)
        self.assertIn("would merge two bookings of one file", out)

    def test_conflict_and_invalid_links(self):
        self.camt("a", [(7, "CRDT", "2025-01-10", "R7", "X", "t")], 0, 7)
        self.camt("b", [(8, "CRDT", "2025-01-10", "R7", "X", "t")], 0, 8)
        code, out, rows, obs = self.books()
        self.assertEqual((code, len(rows)), (1, 2), out)
        self.assertIn("conflict with", rows[1]["open"])
        self.decide(f"{obs[0]['id']};{obs[1]['id']};same", "123456789abc:1;123456789abc:2;same")
        code, out, rows, _ = self.books()                                    # amounts differ: refused
        self.assertEqual((code, len(rows)), (1, 2), out)
        self.assertEqual(out.count("INVALID LINKS.csv"), 2, out)


class TestCoverage(Books):
    def months(self, feb_closing=0, skip_feb=False):
        self.camt("jan", [(100, "CRDT", "2025-01-15", "J", "X", "t")], 0, 100, "2025-01-01", "2025-01-31")
        if not skip_feb:                                                     # a month without bookings
            self.camt("feb", [], 100, 100 + feb_closing, "2025-02-01", "2025-02-28")
        self.camt("mar", [(10, "DBIT", "2025-03-10", "M", "Y", "t")], 100, 90, "2025-03-01", "2025-03-31")
        self.books()
        return quiet(session.status, self.root)[1]

    def test_month_without_bookings_counts(self):
        self.assertIn("mlp-giro-0001: until 2025-03-31\n", self.months())

    def test_missing_month_is_a_gap(self):
        self.assertIn("mlp-giro-0001: until 2025-03-31; 1 gap(s): 2025-02-01…2025-02-28", self.months(skip_feb=True))

    def test_failed_file_closes_no_gap(self):
        self.assertIn("1 gap(s): 2025-02-01…2025-02-28", self.months(feb_closing=5))

    def test_complete_from_and_balance_dates(self):
        (self.root / "PROFILE.md").write_text(PROFILE.replace("| self | camt | | |", "| self | camt | 2024-12-01 | |"))
        self.camt("jan", [(1, "CRDT", "2025-01-15", "J", "X", "t")], 0, 1, "2025-01-03", "2025-01-31", span=False)
        self.books()
        rows = list(csv.DictReader((self.root / "build/coverage.csv").read_text().splitlines(), delimiter=";"))
        self.assertEqual([(r["from"], r["to"], r["check"]) for r in rows], [("2025-01-03", "2025-01-31", "OK")])
        self.assertIn("1 gap(s): 2024-12-01…2025-01-02", quiet(session.status, self.root)[1])


class TestSettlement(Books):
    def giro(self, *days):
        entries = [(21.79, "DBIT", d, f"P{i}", "Haspa", "KREDITKARTENABRECHNUNG") for i, d in enumerate(days)]
        entries.append((50, "DBIT", "2025-03-12", "S", "Stadtwerke", "Abschlag"))
        self.camt("giro", entries, 200, 200 - 50 - 21.79 * len(days), "2025-03-01", "2025-04-30")

    def spending(self, rows):
        return sum(Decimal(r["amount"]) for r in rows if Decimal(r["amount"]) < 0 and not r["settles"])

    def test_card_purchases_count_once(self):
        self.put(f"{CARD}/statement.txt", STATEMENT)
        self.giro("2025-03-11")
        code, out, rows, obs = self.books()
        self.assertEqual(code, 0, out)
        payment = next(r for r in rows if r["ref"] == "P0")
        self.assertTrue(payment["settles"].endswith(":0"))                  # the giro payment stays a movement
        self.assertEqual(self.spending(rows), Decimal("-71.79"))           # 21.42 + 0.37 + 50
        self.assertIn("1 of 1 card statements settled", out)

    def test_missing_card_data_keeps_the_payment(self):
        self.giro("2025-03-11")
        code, out, rows, _ = self.books()
        self.assertEqual((code, self.spending(rows)), (0, Decimal("-71.79")), out)

    def test_unmatched_statement_turns_open_once_the_payer_is_read(self):
        self.put(f"{CARD}/statement.txt", STATEMENT)
        self.giro("2025-04-08")                                              # 34 days after: beyond the rule
        code, out, rows, _ = self.books()
        self.assertEqual(code, 1, out)
        self.assertIn("no payment found up to 2025-04-04", out)
        self.assertIn("21.79 provisional", out)                              # the card purchases are in doubt
        payment = next(r["id"] for r in rows if r["ref"] == "P0")
        statement = next(r["open"].split()[2] for r in rows if r["open"])
        self.decide(f"{payment};{statement};settles")
        code, out, rows, _ = self.books()
        self.assertEqual((code, self.spending(rows)), (0, Decimal("-71.79")), out)
        self.decide(f"-;{statement};settles")                                 # paid from an account not read
        code, out, rows, _ = self.books()
        self.assertEqual((code, self.spending(rows)), (0, Decimal("-93.58")), out)

    def test_two_possible_payments_stay_open(self):
        self.put(f"{CARD}/statement.txt", STATEMENT)
        self.giro("2025-03-11", "2025-03-20")
        code, out, rows, obs = self.books()
        self.assertEqual(code, 1, out)
        self.assertEqual(sum(1 for r in rows if r["open"].startswith("settles")), 2)
        statement = next(r["open"].split()[1].rstrip("?") for r in rows if r["open"])
        first = next(r["id"] for r in rows if r["ref"] == "P0")
        self.decide(f"{first};{statement};settles")
        code, out, rows, _ = self.books()
        self.assertEqual((code, self.spending(rows)), (0, Decimal("-93.58")), out)   # the second debit is real


class TestRobustness(Books):
    def test_missing_pdf_tool_skips_only_pdfs(self):
        def no_tool(*args):
            raise FileNotFoundError("pdftotext")
        transactions.PARSERS["haspa-card-pdf"] = ("abrechnung/**/*.txt", no_tool)
        self.put(f"{CARD}/statement.txt", STATEMENT)
        self.camt("jan", [(7, "CRDT", "2025-01-10", "R7", "X", "t")], 0, 7)
        code, out, rows, _ = self.books()
        self.assertEqual((code, len(rows)), (0, 1), out)
        self.assertIn("pdftotext missing", (self.root / "build/check-report.txt").read_text())

    def test_status_survives_a_bad_profile(self):
        self.camt("jan", [(7, "CRDT", "2025-01-10", "R7", "X", "t")], 0, 7)
        self.books()
        (self.root / "PROFILE.md").write_text(PROFILE.replace("| self | camt | | |", "| self | camt | soon | |"))
        code, out = quiet(session.status, self.root)
        self.assertIn("must be YYYY-MM-DD", out)

    def test_filing_stops_when_raw_lost_everything(self):
        self.put("inbox/Konto_1234567890-Auszug_2024_3.pdf", "march")
        quiet(filing.run, self.root, apply=True)
        next((self.root / "raw/bank").rglob("*.pdf")).unlink()
        self.put("inbox/Konto_1234567890-Auszug_2024_4.pdf", "april")
        code, out = quiet(filing.run, self.root, apply=True)
        self.assertEqual(code, 1, out)


class TestBatch(Books):
    def batch(self, *amounts):
        items = "".join(f"<TxDtls><Amt Ccy=\"EUR\">{a:.2f}</Amt><CdtDbtInd>DBIT</CdtDbtInd><RltdPties><Cdtr><Pty>"
                        f"<Nm>Payee {i}</Nm></Pty></Cdtr></RltdPties><RmtInf><Ustrd>item {i}</Ustrd></RmtInf></TxDtls>"
                        for i, a in enumerate(amounts))
        entry = (f"<Ntry><Amt Ccy=\"EUR\">30.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2025-01-05</Dt></BookgDt>"
                 f"<AcctSvcrRef>B1</AcctSvcrRef><NtryDtls>{items}</NtryDtls></Ntry>")
        f = self.put("raw/b.xml", camt_xml(GIRO, [], 100, 70, extra=entry))
        return parse_camt(f, "mlp-giro-0001", "raw/b.xml")

    def test_items_that_add_up_are_split(self):
        rows, check = self.batch(10, 20)
        self.assertTrue(check["ok"], check)
        self.assertEqual([(r["amount"], r["counterparty"], r["text"]) for r in rows],
                         [(Decimal("-10.00"), "Payee 0", "item 0"), (Decimal("-20.00"), "Payee 1", "item 1")])

    def test_other_batches_stay_whole(self):
        rows, check = self.batch(10, 15)
        self.assertTrue(check["ok"], check)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["text"].startswith("batch of 2, not itemized"))


class TestReviewFindings(Archive):
    """Counter-cases from the external review of 0.1.0 (F01–F09)."""

    def file(self):
        return quiet(filing.run, self.root, apply=True)

    def test_baseline_survives_imports(self):                                   # F01
        self.put("inbox/Konto_1234567890-Auszug_2024_3.pdf", "statement")
        self.file()
        doc = self.root / "raw/bank/haspa-giro-7890/kontoauszug/2024/2024-03_haspa-giro-7890_kontoauszug.pdf"
        doc.write_text("tampered")
        self.put("inbox/Konto_1234567890-Auszug_2024_4.pdf", "next statement")
        code, out = self.file()
        self.assertEqual(code, 1, out)
        self.assertIn("STOP", out)
        self.assertTrue((self.root / "inbox/Konto_1234567890-Auszug_2024_4.pdf").exists())
        self.assertIn("CHANGED", quiet(filing.verify, self.root)[1])
        doc.write_text("statement")
        self.put("raw/bank/haspa-giro-7890/kontoauszug/2024/stray.pdf", "x")      # foreign file
        self.assertEqual(self.file()[0], 1)

    def test_documents_without_manifest_fail(self):                             # F01, F09
        self.put("raw/belege/vertrag/2024/a.pdf", "x")
        code, out = quiet(filing.verify, self.root)
        self.assertEqual(code, 1, out)
        self.assertIn("NO MANIFEST", out)

    def test_failed_file_excluded(self):                                        # F02
        self.put("raw/bank/test-giro-3000/camt052/2025/x.xml", camt_xml(
            "DE89370400440532013000", [(10, "CRDT", "2025-01-03", "R1", "X", "t")], 100, 150))
        code, out = quiet(transactions.run, self.root)
        self.assertEqual(code, 1, out)
        rows = (self.root / "build/transactions.csv").read_text().splitlines()
        self.assertEqual(len(rows), 1, rows)                                    # header only

    def test_all_reports_and_their_accounts(self):                              # F04, F05
        same = self.put("raw/same.xml", two_reports("DE89370400440532013000", "DE89370400440532013000"))
        rows, check = parse_camt(same, "test-giro-3000", "raw/same.xml", ["89370400440532013000"])
        self.assertEqual((len(rows), check["ok"]), (2, True))
        mixed = self.put("raw/mixed.xml", two_reports("DE89370400440532013000", "DE12672300004000000001"))
        rows, check = parse_camt(mixed, "test-giro-3000", "raw/mixed.xml", ["89370400440532013000"])
        self.assertFalse(check["ok"], check)

    def test_content_iban_beats_file_name(self):                                # F05
        name = "01_01_2025-01_01_2026_C52_DE12672300004000000001_EUR.xml"
        self.put(f"inbox/{name}", camt_xml("DE89370400440532013000", [], 0, 0))
        plan = filing.plan_bank(self.root / "inbox" / name, Accounts(load(self.root)))
        self.assertEqual(plan[0], "test-giro-3000")

    def test_zip_members_with_same_name(self):                                  # F06
        import zipfile
        with zipfile.ZipFile(self.root / "inbox/post.zip", "w") as z:
            z.writestr("one/invoice.pdf", "first")
            z.writestr("two/invoice.pdf", "second")
        self.file()
        files = sorted(p.read_text() for p in (self.root / "inbox/unzipped_post").iterdir())
        self.assertEqual(files, ["first", "second"])

    def test_index_keeps_categories_apart(self):                                # F07
        self.put("inbox/a.pdf", "invoice")
        self.put("inbox/b.pdf", "contract")
        self.put("raw/CATALOG.csv", "original;date;category;source;description;doc_no;year\n"
                                    "a.pdf;2025-02-01;rechnung;acme;service;;\n"
                                    "b.pdf;2025-02-01;vertrag;acme;service;;\n")
        self.file()
        index = {r.split(";")[0]: r for r in (self.root / "raw/INDEX.csv").read_text().splitlines()[1:]}
        self.assertIn(";a.pdf;rechnung;", index["belege/rechnung/2025/2025-02-01_acme_service.pdf"])
        self.assertIn(";b.pdf;vertrag;", index["belege/vertrag/2025/2025-02-01_acme_service.pdf"])

    def test_catalog_cannot_leave_raw(self):                                    # F08
        self.put("inbox/x.pdf", "x")
        self.put("raw/CATALOG.csv", "original;date;category;source;description;doc_no;year\n"
                                    "x.pdf;2025-02-01;../../tax;a;b;;\n")
        code, out = self.file()
        self.assertIn("INVALID CATALOG ROW (1)", out)
        self.assertTrue((self.root / "inbox/x.pdf").exists())
        self.assertFalse((self.root / "tax").exists())

    def test_interrupted_import_is_resumable(self):                             # F09
        self.put("inbox/Konto_1234567890-Auszug_2024_3.pdf", "march")
        self.put("inbox/Konto_1234567890-Auszug_2024_4.pdf", "april")
        real, calls = filing.shutil.move, []

        def failing_move(src, dst):
            calls.append(src)
            if len(calls) == 2:
                raise OSError("disk unplugged")
            return real(src, dst)
        filing.shutil.move = failing_move
        try:
            with self.assertRaises(OSError):
                self.file()
        finally:
            filing.shutil.move = real
        self.assertEqual(quiet(filing.verify, self.root)[0], 0)                 # filed part is recorded
        self.assertEqual(self.file()[0], 0)                                     # rerun completes
        self.assertEqual(len((self.root / "raw/MANIFEST.sha256").read_text().splitlines()), 2)

    def test_interrupted_between_move_and_record(self):                         # F09: red, then resumable
        self.put("inbox/Konto_1234567890-Auszug_2024_3.pdf", "march")
        real = filing.shutil.move

        def move_then_crash(src, dst):
            real(src, dst)
            raise OSError("power cut")
        filing.shutil.move = move_then_crash
        try:
            with self.assertRaises(OSError):
                self.file()
        finally:
            filing.shutil.move = real
        code, out = quiet(filing.verify, self.root)
        self.assertEqual(code, 1, out)
        self.assertIn("MANIFEST: raw/bank/haspa-giro-7890/kontoauszug/2024/", out)       # NO or NOT IN
        stray = next((self.root / "raw/bank").rglob("*.pdf"))                   # REFERENCE › Troubleshooting
        shutil.move(str(stray), str(self.root / "inbox" / stray.name))
        self.put("raw/CATALOG.csv", "original;date;category;source;description;doc_no;year\n"
                                    f"{stray.name};2024-03-28;bank/haspa-giro-7890/kontoauszug;haspa;kontoauszug;;\n")
        self.assertEqual(self.file()[0], 0)
        self.assertEqual(quiet(filing.verify, self.root)[0], 0)

    def test_unsafe_account_slug(self):
        (self.root / "PROFILE.md").write_text(PROFILE.replace("| mlp-postbox |", "| ../postbox |"))
        code, out = self.file()
        self.assertEqual(code, 1, out)
        self.assertIn("must be lowercase", out)
        (self.root / "PROFILE.md").write_text(PROFILE.replace("| self | camt | | |", "| self | camt | 1.1.2025 | |"))
        self.assertIn("must be YYYY-MM-DD", self.file()[1])


class TestSession(Archive):
    def test_lifecycle(self):
        self.assertEqual(quiet(session.init, self.root)[0], 0)
        for f in ("STATE.md", "LEARNINGS.md", "raw/CATALOG.csv", ".git"):
            self.assertTrue((self.root / f).exists(), f)
        self.assertIn(f"Updated: {date.today().isoformat()}", (self.root / "STATE.md").read_text())

        self.put("tax/note.md", "x")
        self.assertEqual(quiet(session.checkpoint, self.root, "note")[0], 1)          # STATE.md unchanged
        self.assertEqual(quiet(session.checkpoint, self.root, "note", same_state=True)[0], 0)

        state = (self.root / "STATE.md").read_text().replace(
            "## Open\n", f"## Open\n- {date.today() - timedelta(days=1)} · overdue thing\n"
                         f"- {date.today() + timedelta(days=3)} · due thing\n- undated thing\n")
        (self.root / "STATE.md").write_text(state)
        self.assertEqual(quiet(session.checkpoint, self.root, "state")[0], 0)
        code, out = quiet(session.status, self.root)
        self.assertIn("UNCLOSED SESSION", out)
        self.assertIn(f"Last activity: {date.today().isoformat()}, 0 days ago", out)
        self.assertIn("overdue thing", out)
        self.assertIn("1 open item(s) without a review date", out)

        code, out = quiet(session.close, self.root, "Set up and tested.")
        self.assertEqual(code, 0, out)
        tags = subprocess.run(["git", "tag", "-l", "session/*"], cwd=self.root,
                              capture_output=True, text=True).stdout.split()
        self.assertEqual(tags, [f"session/{date.today().isoformat()}"])
        self.assertNotIn("UNCLOSED", quiet(session.status, self.root)[1])
        self.assertIn("already closed", quiet(session.close, self.root, "again")[1])

    def test_not_set_up(self):
        (self.root / "PROFILE.md").unlink()
        self.assertIn("NOT SET UP", quiet(session.status, self.root)[1])


if __name__ == "__main__":
    unittest.main()
