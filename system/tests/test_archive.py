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
        kept, removed, conflicts = transactions.dedupe(rows)
        self.assertEqual((len(kept), removed, conflicts), (5, 3, []))

    def test_counterparty_and_conflicts(self):
        bakery, bookshop = self.tx("", "f1", ""), self.tx("", "f2", "")
        bakery["counterparty"], bookshop["counterparty"] = "BAKERY", "BOOKSHOP"
        kept, removed, _ = transactions.dedupe([bakery, bookshop])          # same day and amount, other shops
        self.assertEqual((len(kept), removed), (2, 0))
        kept, removed, conflicts = transactions.dedupe([self.tx("R9", "f1"), self.tx("R9", "f2", amount="11")])
        self.assertEqual((len(kept), len(conflicts)), (2, 1))              # same reference, other amount


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

    def test_interrupted_import_stays_consistent(self):                         # F09
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

    def test_unsafe_account_slug(self):
        (self.root / "PROFILE.md").write_text(PROFILE.replace("| mlp-postbox |", "| ../postbox |"))
        code, out = self.file()
        self.assertEqual(code, 1, out)
        self.assertIn("must be lowercase", out)


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
