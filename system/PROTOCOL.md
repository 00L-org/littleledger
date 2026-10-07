# Protocol

This folder is a personal finance archive that you keep in order together with its owner. Follow this protocol in every session, whatever tool you run in.

## Principles
- Files are the only memory. Assume nothing from earlier chats; whatever the next session needs goes into a file.
- The session can end at any moment, so keep STATE.md true after every block of work, not only at the end.
- Use the language and style set in PROFILE.md for everything meant for people: replies, letters, workbooks. Write the archive's working files, commit messages and session summaries in English, keeping German legal and banking terms as they are.
- You prepare facts; tax and legal decisions belong to the owner and their tax advisor.

## Folders
- raw/: originals. Documents enter only through `file`; never edit, rename, move or delete one. The files directly in raw/ are metadata kept by `file`; you only add rows to raw/CATALOG.csv.
- inbox/: landing zone, empty once everything is filed.
- tax/: hand-made work. Never overwrite it; generate into build/ and let the owner take over.
- build/: derived and disposable; regenerate freely.
- scripts/: tools of this archive only.
- system/: belongs to the template and is replaced on update (system/UPDATE.md). Never put personal data or local changes there.

## Start
1. Run `python3 system/archive.py status` and keep its output for the briefing. If python3 or git is missing, or status says NOT SET UP, follow system/INIT.md instead.
2. Read PROFILE.md, STATE.md and LEARNINGS.md in full.
3. If status reports an unclosed session or uncommitted changes, do Catch-up first.
4. Brief the owner in at most eight lines: time since the last activity, what a catch-up found, overdue items and items due within seven days, what you are waiting for, the inbox, and your proposal for today.
5. After a gap of more than 30 days, add a short reminder of how the archive works and ask what happened meanwhile: letters, payments, deadlines, new accounts.

## During work
- After every finished block, update STATE.md and run `python3 system/archive.py checkpoint "<what changed>"`.
- Put results, decisions and open questions into files before you report them as done.
- When the owner corrects you, a step fails, or you take a detour, add one line under New in LEARNINGS.md at once.
- Derive every status from the sources; never carry one forward unchecked.
- Before calling anything missing, unpaid or wrong, read the source and confirm that the statements cover the period (`status` › Coverage).
- Mark placeholder values with PLACEHOLDER and list them under Open; never file a document on a placeholder.
- Version everything that leaves the archive (v1, v2) and record under In force who received which version.
- Keep helper scripts in scripts/ or delete them deliberately; never leave them in temporary places.
- Commit locally only: never add a remote, push, rebase or rewrite history.

## STATE.md
- Situation: the big picture, at most three lines.
- Now: what is in progress and the next step, at most three lines; rewrite it at every checkpoint.
- Open: one item per line, `- YYYY-MM-DD · item`. The date is when the item must come up again: a week before a deadline, the day to follow up, or the day to reconsider. Every open item has a date.
- In force: decisions that still apply, `- YYYY-MM-DD · decision`; remove one when it no longer applies.
- Remove an item only when nothing is left to do, and name it in the checkpoint message.
- Keep it brief: one line per item; details belong in the files they concern.

## Close
Close when the owner signals the end; offer to close when a block of work is done and nothing else is in progress. To close:
1. Checkpoint.
2. If LEARNINGS.md is over budget, compact it.
3. If your tool can reach the owner's calendar, offer to enter the Open items of the next four weeks on their dates, with short titles only.
4. Run `python3 system/archive.py close "<summary, at most three lines>"` and give the owner the summary in their language.

## Catch-up
Sessions often end without closing; nothing is lost because STATE.md was kept current.
1. Inspect uncommitted changes and the commits after the last session tag (`git status`, `git diff`, `git log`). Commit leftovers with `checkpoint "Recovered unfinished work" --same-state`, or update STATE.md first if they change it.
2. Run close with a summary of that session, ending in "(catch-up)".
3. Bring STATE.md in line with what you found and checkpoint.

## LEARNINGS.md
- Rules are binding. Observations go under New, one line each: `- YYYY-MM-DD · observation → lesson`.
- To compact: an observation becomes a rule only if it recurred or the owner confirmed it; otherwise delete it (git keeps it). Change rules one at a time, never rewrite the file, and show the owner the diff.
- A rule a script can enforce belongs in the script; a rule that would help every archive belongs in the template. Propose either to the owner.

## Commands
`python3 system/archive.py` status · checkpoint "message" [--same-state] · close "summary" · init · file [--apply] · transactions · verify. Formats, filing and troubleshooting: system/REFERENCE.md.
