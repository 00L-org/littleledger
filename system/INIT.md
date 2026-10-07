# Init

Follow this once, when python3 or git is missing or `status` says NOT SET UP. Goal: a working archive after about ten minutes of questions. Ask only what setup needs; everything else becomes a dated Open item.

## 1. Check the tools
Run `python3 --version` (3.9 or newer), `git --version` and `pdftotext -v` without commenting on it. If Python or git is missing, explain how to install it on the owner's system (macOS: `xcode-select --install`) and continue once it works. Missing pdftotext only blocks reading PDF statements: record it as an Open item (macOS: `brew install poppler`).

## 2. Welcome
Use the language the owner wrote in. In at most eight lines, say:
- what the archive does: keeps statements and documents in this folder, names and checks them, builds one table of all transactions, tracks deadlines and open matters, answers questions about all of it, and remembers between sessions in any AI tool that can open the folder;
- what it does not do: no bank logins, no uploads by the archive itself (the AI tool reads the files it works on), no tax or legal advice;
- how it works: put files into inbox/ and say "start"; the assistant does the rest; git records every change, on this computer only.
Then ask whether to set it up now.

## 3. Ask
Ask in three short rounds and offer a default wherever one makes sense. Accept "later" for everything except name and language, and turn each "later" into an Open item dated four weeks ahead, or a week before a related deadline if that comes first.
1. Communication: name; language; style (short bullet points or explanations; how much detail).
2. Purpose and situation: what the archive should do first (overview of money in and out, tax return, documents for a tax advisor, rental property, other) and what later; income types (employment, self-employment, rental, capital, abroad); tax advisor (none, or name and what they handle); years that matter.
3. Accounts, one by one: bank; kind (current account, savings, credit card, depot); full IBAN, or the last four digits of a card; whose (own, joint, someone else's); private, business or mixed; which exports the bank offers (camt XML, PDF statements, CSV); from which day its statements should be complete (default: the first day of the first year that matters).
Finish with one question: what is pending right now (deadlines, letters, expected payments)?
Record ideas beyond the first goal as Open items as well; do not build them now.

## 4. Create
1. Write PROFILE.md from system/templates/PROFILE.md (fields: system/REFERENCE.md › Profile and › Accounts). Name each account `<bank>-<kind>-<last4>` in lowercase ASCII with a short bank name, e.g. `sparkasse-giro-1234`; set its parser from the exports it offers and `complete from` from the answer; put private, business or mixed into the note.
2. Run `python3 system/archive.py init`.
3. Fill STATE.md: Situation from the answers; Open with the owner's deadlines, one "export statements" item per account dated today, one item to make sure this folder is backed up, and every "later"; Now with the next step.
4. Checkpoint.

## 5. First filing
If the owner has files at hand, ask them to put the files into inbox/, then follow system/REFERENCE.md › Filing. Otherwise explain how to export from their bank: camt.052/053 XML for the longest period offered, plus PDF statements as legal originals; most banks keep only 90 days to 13 months online, so export soon.

## 6. Close
Close per system/PROTOCOL.md and end with what to do next time: put files into inbox/ and say "start".
