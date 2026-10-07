# Changes

Each version lists what changed and what an existing archive must do (system/UPDATE.md, step 6).

## 0.2.2 · 2026-10-07
Scope stated in README and REFERENCE. Instance changes: none.

## 0.2.1 · 2026-10-07
Renamed to littleledger; code and documentation under MIT. Added contribution guidance and tests on Ubuntu and macOS. Instance changes: none.

## 0.2.0 · 2026-10-07
Every booking keeps its sources, card payments are linked to their statements, and gaps in the statements show:
- build/observations.csv lists every booking read with a stable id (file checksum and position); build/transactions.csv gains the columns id, merged, settles and open.
- Bookings of two files are merged automatically only on equal bank reference, day and amount. Look-alikes without a reference, which 0.1.1 merged silently, and conflicting references stay apart and are marked open until a line in LINKS.csv decides.
- A payment that settles a card statement is linked to it (column settles), so spending counts the card purchases once; a statement whose payment cannot be found becomes an open question.
- build/coverage.csv holds the period each statement states; `transactions` and `status` show each account's last covered day and its gaps. New PROFILE.md column `complete from`.
- camt batch entries are split where their items add up, else marked as not itemized; identical copies of a bank file are skipped.
- An unreadable file fails alone instead of stopping `transactions`; without pdftotext, PDF statements show as SKIP. `status` shows problems in PROFILE.md. Filing now also stops when raw/ has lost every document.
- Filing still records a document right after moving it; an interruption in between leaves raw/ red (NOT IN MANIFEST) until the file is filed again, as REFERENCE.md › Troubleshooting describes.
Instance changes:
1. Copy system/templates/LINKS.csv into the archive root.
2. In PROFILE.md, add the column `complete from` after parser in the accounts table; fill it where the owner expects complete statements.
3. Make scripts that read build/transactions.csv accept the new columns.

## 0.1.1 · 2026-10-07
Fixes from an external review:
- Filing refuses to run while raw/ differs from raw/MANIFEST.sha256, records each document right after moving it and never rewrites manifest lines; documents without a manifest fail verify.
- Files that fail their check stay out of build/transactions.csv.
- camt: every report is read and must carry the account's IBAN; when filing, the IBAN inside beats the file name.
- Deduplication also compares the counterparty; the same bank reference with other content is kept and reported as CONFLICT.
- ZIP members with the same name no longer overwrite each other.
- raw/INDEX.csv links catalog rows by full path; invalid catalog rows and unsafe account slugs are refused.
Instance changes: none.

## 0.1.0 · 2026-10-07
First release. Instance changes: none.
