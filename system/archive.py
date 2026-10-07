#!/usr/bin/env python3
"""finance-archive command line. Run from anywhere: python3 system/archive.py <command>."""
import sys
from pathlib import Path

from lib import filing, session, transactions

ROOT = Path(__file__).resolve().parent.parent
USAGE = """usage: python3 system/archive.py <command>
  status                            briefing data for the start of a session
  checkpoint "message" [--same-state]  commit all changes; STATE.md must have changed
  close "summary"                   mark the session as closed (annotated git tag)
  init                              set up a new archive once PROFILE.md exists
  file [--apply]                    file inbox/ into raw/ (dry run without --apply)
  transactions                      rebuild build/transactions.csv and build/check-report.txt
  verify                            check raw/ against raw/MANIFEST.sha256"""


def main(argv: list) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(USAGE)
        return 0
    cmd, flags = argv[0], {a for a in argv[1:] if a.startswith("--")}
    text = " ".join(a for a in argv[1:] if not a.startswith("--"))
    commands = {
        "status": lambda: session.status(ROOT),
        "checkpoint": lambda: session.checkpoint(ROOT, text, "--same-state" in flags),
        "close": lambda: session.close(ROOT, text),
        "init": lambda: session.init(ROOT),
        "file": lambda: filing.run(ROOT, apply="--apply" in flags),
        "transactions": lambda: transactions.run(ROOT),
        "verify": lambda: filing.verify(ROOT),
    }
    if cmd not in commands:
        print(USAGE)
        return 2
    return commands[cmd]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
