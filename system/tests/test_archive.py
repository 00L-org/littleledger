"""Self-test with synthetic data only. Run: python3 -m unittest discover -s system/tests"""
import contextlib
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

from lib import filing, session, transactions  # noqa: E402
from lib.accounts import Accounts, load  # noqa: E402
from lib.parsers import parse_camt, parse_haspa_card_text, parse_haspa_text  # noqa: E402

PROFILE = """# Profile

## Owner
- Name: Erika Mustermann
- Language: German
- Style: short bullet points

## Accounts
| account | bank | kind | id | owner | parser | note |
|---|---|---|---|---|---|---|
| `haspa-giro-7890` | Haspa | giro | DE02 2005 0550 1234 5678 90 | self | haspa-pdf | |
| haspa-mastercard-1111 | Haspa | mastercard | 5232 **** **** 1111 | self | haspa-card-pdf | |
| mlp-giro-0001 | MLP | giro | DE12672300004000000001 | self | camt | |
| mlp-card-777 | MLP | card | …777 | self | | |
| mlp-postbox | MLP | postbox | | self | | letters |
| test-giro-3000 | Testbank | giro | DE89370400440532013000 | Max Mustermann | camt | |

## Rules
"""

NS = "urn:iso:std:iso:20022:tech:xsd:camt.052.001.08"


def camt_xml(iban, entries, opening, closing, frm="2025-01-02", to="2025-01-31"):
    """entries: (amount, CRDT|DBIT, day, ref or None, counterparty, text)"""
    def bal(code, amount):
        cd = "CRDT" if amount >= 0 else "DBIT"
        return (f"<Bal><Tp><CdOrPrtry><Cd>{code}</Cd></CdOrPrtry></Tp><Amt Ccy=\"EUR\">{abs(amount):.2f}</Amt>"
                f"<CdtDbtInd>{cd}</CdtDbtInd><Dt><Dt>{frm}</Dt></Dt></Bal>")
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
            f"<FrToDt><FrDtTm>{frm}T00:00:00</FrDtTm><ToDtTm>{to}T23:59:59</ToDtTm></FrToDt>"
            f"<Acct><Id><IBAN>{iban}</IBAN></Id></Acct>{bal('OPBD', opening)}{bal('CLBD', closing)}{body}"
            f"</Rpt></BkToCstmrAcctRpt></Document>")


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


class TestDedupe(unittest.TestCase):
    def tx(self, ref, source, text="t", amount="10", day="2025-01-02"):
        return {"account": "a", "booking_date": day, "amount": Decimal(amount), "text": text,
                "ref": ref, "source_file": source}

    def test_rules(self):
        rows = [self.tx("R1", "f1"), self.tx("R1", "f2"),                    # overlap with reference
                self.tx("NONREF", "f1", "rent"), self.tx("NONREF", "f1", "fee"),   # distinct, no reference
                self.tx("", "f1", "coffee"), self.tx("", "f1", "coffee"),    # identical real twins
                self.tx("", "f2", "coffee"), self.tx("", "f2", "coffee")]    # the same twins again
        kept, removed = transactions.dedupe(rows)
        self.assertEqual((len(kept), removed), (5, 3))


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
