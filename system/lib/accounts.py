"""Accounts table from PROFILE.md: the instance tells the tools which accounts exist."""
from __future__ import annotations

import re
from pathlib import Path


def load(root: Path) -> list[dict]:
    """Rows of the first Markdown table under '## Accounts' in PROFILE.md."""
    path = root / "PROFILE.md"
    if not path.exists():
        return []
    rows, header, inside = [], None, False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside, header = line[3:].strip().lower() == "accounts", None
            continue
        line = line.strip()
        if not inside or not line.startswith("|"):
            continue
        cells = [c.strip().strip("`").strip() for c in line.strip("|").split("|")]
        if header is None:
            header = [c.lower() for c in cells]
        elif not all(set(c) <= set("-: ") for c in cells):
            row = dict(zip(header, cells))
            if row.get("account"):
                rows.append(row)
    return rows


def digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


class Accounts:
    """Looks up account slugs by the numbers found in bank file names or files."""

    def __init__(self, rows: list[dict]):
        self.rows = rows

    def find(self, key: str) -> str | None:
        """Slug of the one account whose id ends with the digits of key; None if none or ambiguous."""
        k = digits(key)
        if not k:
            return None
        hits = [r["account"] for r in self.rows
                if any(digits(i).endswith(k) for i in r.get("id", "").split(",") if digits(i))]
        return hits[0] if len(hits) == 1 else None

    def postbox(self, bank: str) -> str | None:
        """Slug of the one account of kind 'postbox' at this bank (for letters without account number)."""
        hits = [r["account"] for r in self.rows
                if r.get("kind", "").lower() == "postbox" and bank.lower() in r.get("bank", "").lower()]
        return hits[0] if len(hits) == 1 else None
