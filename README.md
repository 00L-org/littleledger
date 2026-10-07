# finance-archive

A personal finance archive that an AI assistant keeps in order with you: statements and documents in one local folder, named, checked and versioned; one table of all transactions; deadlines and open matters that come back on time; and a memory that lasts between sessions and across AI tools.

Deutsch: Ordner in Claude Code, Claude Desktop oder Codex öffnen und „Start" sagen. Die KI erklärt alles und richtet das Archiv im Gespräch ein.

## Start
1. Download or clone this folder and open it in an AI tool that works with files: Claude Code, Claude Desktop (Cowork) or Codex.
2. Say "start". The assistant explains the archive, asks a few questions and sets everything up, git included.
3. From then on: put new files into `inbox/` and say "start".

Needs Python 3.9 or newer and git; `pdftotext` (poppler) for PDF statements.

## How it works
- Everything stays on your computer. The archive never logs into banks or clouds, and setup removes every git remote.
- `AGENTS.md` sends every assistant to `system/PROTOCOL.md`: how a session starts, keeps its state and closes.
- Your files: `PROFILE.md` (you and your accounts), `STATE.md` (what is open, each item with a date), `LEARNINGS.md` (what the assistant has learned), `raw/` (originals, never changed), `tax/` (your work).
- `system/` belongs to the template; updating means replacing it (`system/UPDATE.md`).

## Formats
camt.052/053 XML from any bank is read and checked against its balances, as are Hamburger Sparkasse PDF statements (from 2022) and Mastercard statements. All other files are archived with names, index and checksums.

No tax or legal advice.

## License
Code: MIT (`LICENSE`). Documentation: CC BY 4.0.
