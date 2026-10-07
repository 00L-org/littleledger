# Reference

## Layout
```
AGENTS.md, CLAUDE.md   entry points for AI tools; never personalised
PROFILE.md             owner, accounts, standing rules
STATE.md               the present (PROTOCOL.md › STATE.md)
LEARNINGS.md           rules learned in this archive
inbox/                 landing zone, not in git
raw/                   originals and their metadata
  bank/<account>/<kind>/<year>/
  belege/<category>/<year>/
  CATALOG.csv  INDEX.csv  MANIFEST.sha256  DISCARDED.csv
tax/                   hand-made work, one folder per year
build/                 derived and disposable, not in git; build/discarded/ holds duplicates, unpacked archives and discarded files
scripts/               tools of this archive only
system/                the template: protocol, tools, tests
```
Folder and file names are English. Names inside raw/ use German banking and tax terms because they describe German documents.

## Profile
- Owner: Name; Language for conversation and for documents meant for people; Style: format and depth of replies, how to collaborate.
- Purpose: Goals, first and later; Years that matter.
- Situation: Income (employment, self-employment with EÜR or balance sheet and VAT status, rental, capital, abroad); Tax advisor (who, what they handle); further facts every session needs.
- Accounts: the table below.
- Rules: standing instructions for this archive only.

## Accounts
| column | meaning |
|---|---|
| account | slug, lowercase ASCII, ideally `<bank>-<kind>-<last4>`; names the folder raw/bank/<account>/ and never changes |
| bank | institution |
| kind | giro, savings, depot, mastercard, visa, …; `postbox` collects bank letters that carry no account number |
| id | full IBAN for accounts; card number for cards, masking allowed; several separated by commas |
| owner | self, joint, or the holder's name; other people's accounts stay separate in every analysis |
| parser | `camt`, `haspa-pdf`, `haspa-card-pdf`, or empty to archive without reading |
| note | private, business or mixed, and anything else |

A bank file belongs to the account whose id ends with the number in the file name or, for camt, with the IBAN inside the file.

## Filing
1. `python3 system/archive.py file` shows the plan and lists files without a rule as NO RULE.
2. Bank files are recognised by name (Haspa; camt exports of Sparkassen and MLP; MLP; Degussa; OLB), and camt XML from any bank by the IBAN inside.
3. For every other file, read it and append a row to raw/CATALOG.csv: `original;date;category;source;description;doc_no;year`.
   - date: document date, YYYY-MM-DD; for an undated document the date of receipt, noted in the description. year: only if the document belongs to another year than its date.
   - category: folder under raw/belege/, e.g. eingangsrechnung, ausgangsrechnung, finanzamt, steuererklaerung, versicherung, vertrag, vorsorge. `bank/<account>/<kind>` files a bank document to its account, e.g. `bank/dkb-visa-8899/abrechnung` for a card statement PDF. `discard` moves the file to build/discarded/.
   - source: the other party, i.e. the sender of a received and the recipient of a sent document. description: a few words. doc_no: invoice or reference number, if any.
   - Correct a row only while its file is still in inbox/; once filed, the name is final.
4. Classify official letters by document type, not by sender and date: a Grundbuch Vormerkung is not the Umschreibung.
5. `python3 system/archive.py file --apply` unpacks ZIP archives (run it again afterwards), moves the files, moves duplicates to build/discarded/duplicates/ with a line in raw/DISCARDED.csv, and rewrites raw/INDEX.csv and raw/MANIFEST.sha256.
6. Checkpoint. Later, `verify` proves that nothing in raw/ has changed.

## Transactions
- `python3 system/archive.py transactions` reads every account that has a parser and writes build/transactions.csv: account, booking_date, value_date, amount (sign from the holder's view), currency, counterparty, text, type, ref, source_type, source_file.
- build/check-report.txt marks each file OK (its balances add up), FAIL (keep it out of every analysis; fix the parser or get a better file) or SKIP (layout not supported).
- Overlapping exports are deduplicated by the bank reference, or, where none exists (empty, NONREF, NOTPROVIDED), by account, day, amount and text counted per file, so identical real payments survive.
- A credit card settlement on the current account is an internal transfer; the card statement holds the single purchases. Count only one side: the single purchases where the card statement is read, otherwise the settlement.
- Haspa statements come in three layouts; only the one used from 2022 on is parsed, older ones show as SKIP.

## Bank exports
- Best: camt.052 or camt.053 XML for the longest period offered; it carries balances and references, so every file can be checked.
- Keep the PDF statements too: the original format is the legal record. Never convert or delete originals.
- Many banks keep only 90 days to 13 months online: export early and regularly.
- Haspa delivers booked camt.052 as a ZIP with one XML per day; the monthly PDF remains the record.
- MLP CSV exports are archived but not read; export camt.052 instead.

## Troubleshooting
- git cannot remove .git/index.lock (Claude Desktop): request delete permission for this folder; it lapses when the app restarts.
- Commits should name the owner as author; if they do not, set `git config user.name` and `git config user.email` in this folder.
- verify reports NOT IN MANIFEST: a file reached raw/ without `file` and is no document yet; move it to inbox/ and file it.
- pdftotext missing: PDF statements are skipped until poppler is installed (macOS: `brew install poppler`).
- Self-test: `python3 -m unittest discover -s system/tests`.
