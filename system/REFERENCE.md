# Reference

## Layout
```
AGENTS.md, CLAUDE.md   entry points for AI tools; never personalised
PROFILE.md             owner, accounts, standing rules
STATE.md               the present (PROTOCOL.md › STATE.md)
LEARNINGS.md           rules learned in this archive
LINKS.csv              decisions on bookings that the rules leave open (› Transactions)
inbox/                 landing zone, not in git
raw/                   originals and their metadata
  bank/<account>/<kind>/<year>/
  belege/<category>/<year>/
  CATALOG.csv  INDEX.csv  MANIFEST.sha256  DISCARDED.csv
tax/                   hand-made work, one folder per year
build/                 derived and disposable, not in git: the output of `transactions`; build/discarded/ holds
                       duplicates, unpacked archives and discarded files
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
| complete from | first day from which every statement of the account should be in the archive, YYYY-MM-DD; empty: from its first statement |
| note | private, business or mixed, and anything else |

A bank file belongs to the account whose id ends with the number in the file name or, for camt, with the IBAN inside the file.

## Filing
1. `python3 system/archive.py file` shows the plan and lists files without a rule as NO RULE.
2. Bank files are recognised by name (Haspa; camt exports of Sparkassen and MLP; MLP; Degussa; OLB), and camt XML from any bank by the IBAN inside.
3. For every other file, read it and append a row to raw/CATALOG.csv: `original;date;category;source;description;doc_no;year`.
   - date: document date, YYYY-MM-DD; for an undated document the date of receipt, noted in the description. year: only if the document belongs to another year than its date.
   - category: folder under raw/belege/, e.g. eingangsrechnung, ausgangsrechnung, finanzamt, steuererklaerung, versicherung, vertrag, vorsorge. `bank/<account>/<kind>` files a bank document to its account, e.g. `bank/dkb-visa-8899/abrechnung` for a card statement PDF. `discard` moves the file to build/discarded/.
   - source: the other party, i.e. the sender of a received and the recipient of a sent document. description: a few words. doc_no: invoice or reference number, if any.
   - Correct a row only while its file is still in inbox/; once filed, the name is final. Rows with unusable fields are refused as INVALID CATALOG ROW.
4. Classify official letters by document type, not by sender and date: a Grundbuch Vormerkung is not the Umschreibung.
5. `python3 system/archive.py file --apply` refuses to run while raw/ differs from raw/MANIFEST.sha256. It unpacks ZIP archives (run it again afterwards), records each file in raw/MANIFEST.sha256 right after moving it, moves duplicates to build/discarded/duplicates/ with a line in raw/DISCARDED.csv, and rewrites raw/INDEX.csv. Manifest lines are never rewritten. A run interrupted between moving and recording leaves the file NOT IN MANIFEST (Troubleshooting).
6. After filing bank files, run `transactions`. Checkpoint. Later, `verify` proves that nothing in raw/ has changed.

## Transactions
`python3 system/archive.py transactions` reads every account that has a parser and writes into build/:
- observations.csv: every booking read, with its id `<source>:<n>`, the n-th booking of the file whose SHA-256 begins with <source>, and its file's check.
- transactions.csv: one row per booking from the files that passed their check: id, account, booking_date, value_date, amount (sign from the holder's view), currency, counterparty, text, type, ref, source_type, source_file, merged, settles, open.
- coverage.csv: the period each statement states, with its file's check.
- check-report.txt: each file OK (balances add up), FAIL (left out of transactions.csv: unreadable, or its balances or IBAN do not fit; fix the parser or get a better file) or SKIP (layout not supported, pdftotext missing, or a copy of another file); then open questions and coverage.

### Bookings in two files
- A file that passes its check lists each booking once, so bookings of one file are never merged.
- Bookings of two files with equal bank reference, day and amount are merged: the row keeps the first id, and `merged` names the others, whose sources are in observations.csv.
- Kept apart and marked in `open` until LINKS.csv decides: an equal reference with another day or amount (`conflict with <id>`), and equal day, amount, counterparty and text where a reference is missing (`duplicate of <id>?`).
- A batch that one file itemizes and another does not cannot be merged: leave the question open and tell the owner.

### Card statements
- A payment settles a card statement when it is the only booking of exactly the amount due on a non-card account of the card's owner within 30 days after the statement's end, and that statement is the only one it could pay. `settles` names the statement as `<source>:0`.
- The payment stays an account movement, but spending and income totals leave out rows with `settles`: the card purchases are in the table themselves.
- Where several payments fit, each is marked `settles <id>?` in `open`. Where none fits although an account of the owner is read beyond the 30 days, the statement's purchases are marked `payment of <id> not found`. A card whose statements are not read has nothing to link: its payments count as spending.

### LINKS.csv
- One line per decision: `left_id;right_id;kind;basis`. kind: `same` (one booking in two files), `distinct` (unrelated, although a rule paired them; also a payment and a card statement) or `settles` (payment left settles card statement right; left `-` when it was paid from an account that is not read). basis: the evidence, who decided, and when.
- Decide from the sources; ask the owner when they leave it open. Remove a line only when its decision was wrong.
- Totals that include rows with `open` are provisional by those amounts; say so when you report them.

### Coverage
- A statement covers the period it states, never the span of its bookings: camt its report period, or else its opening and closing balance dates; Haspa account and card statements the days after the previous statement's end up to their own end. A file that states no period covers nothing.
- Only files that passed their check cover. FAIL and SKIP files close no gap, although they lie in raw/: check build/coverage.csv before calling a statement missing.
- Gaps are the days from `complete from`, else the first covered day, up to the last covered day that no statement covers. `status` shows each account's last covered day and its gaps.

### Formats
- camt batch entries are split into their items only where each item states an amount and the amounts add up to the entry; otherwise the entry stays one booking, marked `batch of <n>, not itemized`.
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
- verify reports NOT IN MANIFEST or NO MANIFEST: those files reached raw/ unrecorded, copied there by hand or moved by an interrupted `file --apply`, and are no documents yet. Move them to inbox/ and file them; where no rule recognises the name, add a catalog row (category `bank/<account>/<kind>` for bank files). MISSING or CHANGED: restore the file from git (`git checkout -- raw/<path>`).
- `transactions` reports INVALID LINKS.csv lines: they no longer fit the data, often after a parser change, or contradict another line. Find the bookings in build/observations.csv again and correct the line.
- pdftotext missing: PDF statements show as SKIP until poppler is installed (macOS: `brew install poppler`).
- Self-test: `python3 -m unittest discover -s system/tests`.
