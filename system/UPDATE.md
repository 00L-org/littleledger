# Update

An update replaces system/ and nothing else; the owner's files stay as they are.
1. Checkpoint, so the update becomes one clean commit.
2. Get the new template, by download or clone, into a folder outside this archive. Read its system/CHANGES.md from the version in system/VERSION onward.
3. Run `python3 system/archive.py transactions` and keep a copy of build/transactions.csv.
4. Replace system/ with the new one.
5. Run the self-test and `transactions` again; compare with the copy and explain every difference to the owner.
6. Make the instance changes CHANGES.md asks for, then checkpoint "Update system to <version>".
