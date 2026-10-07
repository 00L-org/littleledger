# Changes

Each version lists what changed and what an existing archive must do (system/UPDATE.md, step 6).

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
