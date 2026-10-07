# littleledger

A personal finance archive that an AI assistant keeps in order with you: statements and documents in one local folder, named, checked and versioned; one table of all transactions; deadlines and open matters that come back on time; and a memory that lasts between sessions and across AI tools.

Deutsch: Ordner in Claude Code, Claude Desktop oder Codex öffnen und „Start" sagen. Die KI erklärt alles und richtet das Archiv im Gespräch ein.

## Start
1. Download or clone this folder and open it in an AI tool that works with files: Claude Code, Claude Desktop (Cowork) or Codex.
2. Say "start". The assistant explains the archive, asks a few questions and sets everything up, git included.
3. From then on: put new files into `inbox/` and say "start".

Needs Python 3.9 or newer and git; `pdftotext` (poppler) for PDF statements.

## How it works
- Your files stay in this folder: the archive logs into no bank, uploads nothing, and setup removes every git remote. The AI tool you use does read the files it works on and sends that content to its provider.
- Git records every change but is no backup: back the folder up like any other.
- `AGENTS.md` sends every assistant to `system/PROTOCOL.md`: how a session starts, keeps its state and closes.
- Your files: `PROFILE.md` (you and your accounts), `STATE.md` (what is open, each item with a date), `LEARNINGS.md` (what the assistant has learned), `LINKS.csv` (decisions on bookings), `raw/` (originals, never changed), `tax/` (your work).
- `system/` belongs to the template; updating means replacing it (`system/UPDATE.md`).

## Formats
camt.052/053 XML, the standard export of German banks, is read report by report and checked against its balances and the account's IBAN; files that fail stay out of the transaction table. Hamburger Sparkasse PDF statements (from 2022) and Haspa Mastercard statements are read too. Every booking keeps its sources, card payments are linked to their statements, and gaps between statements show. All other files are archived with names, index and checksums.

No tax or legal advice.

## Contributing
Issues and pull requests are welcome; Wolfgang decides what goes in. Develop in a clone of this repository and keep your own archive in a separate folder: `init` removes git remotes and commits everything in its folder. Do not run `init` in the development checkout.

Use synthetic examples only in issues, pull requests and tests; never include personal statements, account details or credentials.

Run the tests from the repository root:
```sh
python3 -m unittest discover -s system/tests
```
Tests need Python 3.9+ and git, but not `pdftotext`. CI runs them on Ubuntu and macOS using each runner's system Python; this is not a test of every supported Python version.

## License
MIT (`LICENSE`), code and documentation.
