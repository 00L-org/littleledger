"""Session commands: status, checkpoint, close, init. Git is the history; STATE.md is the present."""
from __future__ import annotations

import re
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

from lib import coverage

DUE_DAYS = 7
GAP_DAYS = 30
DEFAULT_BUDGET = 5000


def git(root: Path, *args: str, check: bool = False) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(args)} failed:\n{(r.stderr or r.stdout).strip()}")
    return r.stdout.rstrip() if r.returncode == 0 else ""


def section(text: str, title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}[ \t]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def open_items(state: str):
    """(sorted [(review date, text)], number of open lines without a date)."""
    items, undated = [], 0
    for line in section(state, "Open").splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        m = re.match(r"- (\d{4}-\d{2}-\d{2})\s*[·:–-]?\s*(.*)", line)
        if m:
            items.append((date.fromisoformat(m.group(1)), m.group(2)))
        else:
            undated += 1
    return sorted(items), undated


def last_session(root: Path):
    """(latest session tag or None, its commit date, commits after it)."""
    tag = git(root, "describe", "--tags", "--abbrev=0", "--match", "session/*")
    if not tag:
        return None, None, int(git(root, "rev-list", "--count", "HEAD") or 0)
    return tag, git(root, "log", "-1", "--format=%cs", tag), int(git(root, "rev-list", "--count", f"{tag}..HEAD") or 0)


def budget(root: Path):
    """(characters used, budget) of LEARNINGS.md."""
    path = root / "LEARNINGS.md"
    if not path.exists():
        return 0, DEFAULT_BUDGET
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^Budget:\s*(\d+)", text, re.M)
    return len(text), int(m.group(1)) if m else DEFAULT_BUDGET


def stamp(root: Path) -> None:
    """Set 'Updated:' in STATE.md to today."""
    path = root / "STATE.md"
    text = path.read_text(encoding="utf-8")
    line = f"Updated: {date.today().isoformat()}"
    text = re.sub(r"^Updated:.*$", line, text, count=1, flags=re.M) if re.search(r"^Updated:", text, re.M) \
        else text.replace("\n", f"\n{line}\n", 1)
    path.write_text(text, encoding="utf-8")


def status(root: Path) -> int:
    today = date.today()
    out = [f"Archive status · {today:%a %Y-%m-%d}"]
    if not (root / "PROFILE.md").exists():
        print("\n".join(out + ["NOT SET UP: PROFILE.md is missing. Follow system/INIT.md."]))
        return 0
    if not (root / ".git").exists():
        out.append("NO GIT REPOSITORY: run `python3 system/archive.py init`.")
    last = git(root, "log", "-1", "--format=%cs")
    if last:
        gap = (today - date.fromisoformat(last)).days
        out.append(f"Last activity: {last}, {gap} days ago"
                   + (" -> long gap: explain how the archive works, ask what happened" if gap > GAP_DAYS else ""))
    tag, _, since = last_session(root)
    out.append(f"Last closed session: {tag}" if tag else "No closed session yet.")
    if since:
        out.append(f"UNCLOSED SESSION: {since} commit(s) after the last session tag -> at session start: catch up first")
    dirty = git(root, "status", "--porcelain").splitlines()
    if dirty:
        out.append(f"UNCOMMITTED: {len(dirty)} change(s) -> inspect with git status/diff, then checkpoint")

    state = (root / "STATE.md").read_text(encoding="utf-8") if (root / "STATE.md").exists() else ""
    items, undated = open_items(state)
    overdue = [i for i in items if i[0] < today]
    due = [i for i in items if today <= i[0] <= today + timedelta(days=DUE_DAYS)]
    later = [i for i in items if i[0] > today + timedelta(days=DUE_DAYS)]
    for label, group in (("Overdue", overdue), (f"Due within {DUE_DAYS} days", due)):
        out.append(f"{label}: {len(group) or 'none'}")
        out += [f"  {d} · {t}" for d, t in group]
    out.append(f"Later: {len(later)}" + (f", next {later[0][0]}" if later else ""))
    if undated:
        out.append(f"WARNING: {undated} open item(s) without a review date")

    inbox = root / "inbox"
    files = [p for p in inbox.rglob("*") if p.is_file() and not p.name.startswith(".")] if inbox.exists() else []
    out.append(f"Inbox: {len(files) or 'empty'}" + (" file(s) -> file them" if files else ""))
    out += coverage.status(root)
    used, limit = budget(root)
    out.append(f"LEARNINGS.md: {used} of {limit} characters" + (" -> OVER BUDGET: compact" if used > limit else ""))
    print("\n".join(out))
    return 0


def checkpoint(root: Path, message: str, same_state: bool = False) -> int:
    if not message:
        print('Usage: checkpoint "what changed" [--same-state]')
        return 2
    changed = [line[3:].strip('"') for line in git(root, "status", "--porcelain").splitlines()]
    if not changed:
        print("Nothing to commit.")
        return 0
    state_changed = "STATE.md" in changed
    if not state_changed and not same_state:
        print("STATE.md is unchanged. Update it first, or pass --same-state if it is still accurate.")
        return 1
    if state_changed:
        stamp(root)
    git(root, "add", "-A", check=True)
    git(root, "commit", "-q", "-m", message, check=True)
    print(f"Checkpoint {git(root, 'log', '-1', '--format=%h')}: {message}")
    return 0


def close(root: Path, summary: str) -> int:
    if not summary:
        print('Usage: close "summary in up to three lines"')
        return 2
    if git(root, "status", "--porcelain"):
        print("Uncommitted changes: checkpoint first.")
        return 1
    if not git(root, "rev-parse", "--verify", "-q", "HEAD"):
        print("No commits yet: nothing to close.")
        return 0
    tag, _, since = last_session(root)
    if tag and not since:
        print(f"Nothing new since {tag}: the session is already closed.")
        return 0
    day = git(root, "log", "-1", "--format=%cs")          # date of the session's last commit
    name, n = f"session/{day}", 2
    while git(root, "tag", "-l", name):
        name, n = f"session/{day}-{n}", n + 1
    git(root, "tag", "-a", name, "-m", summary, check=True)
    used, limit = budget(root)
    print(f"Closed {name}." + (f" LEARNINGS.md is over budget ({used}/{limit}): compact it next session." if used > limit else ""))
    return 0


def init(root: Path) -> int:
    templates = Path(__file__).resolve().parents[1] / "templates"
    profile = root / "PROFILE.md"
    if not profile.exists():
        print("Write PROFILE.md first (from system/templates/PROFILE.md, see system/INIT.md).")
        return 1
    created = []
    for d in ("inbox", "raw", "build"):
        (root / d).mkdir(exist_ok=True)
    for name, target in (("STATE.md", root / "STATE.md"), ("LEARNINGS.md", root / "LEARNINGS.md"),
                         ("LINKS.csv", root / "LINKS.csv"), ("CATALOG.csv", root / "raw" / "CATALOG.csv")):
        if not target.exists():
            shutil.copyfile(templates / name, target)
            created.append(target.relative_to(root).as_posix())
    stamp(root)

    if not (root / ".git").exists():
        if subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root).returncode:
            git(root, "init", "-q", check=True)
            git(root, "symbolic-ref", "HEAD", "refs/heads/main", check=True)
        created.append(".git")
    removed = git(root, "remote").split()
    for r in removed:                    # private data must never be pushed anywhere
        git(root, "remote", "remove", r, check=True)
    if not git(root, "config", "user.name"):
        m = re.search(r"^- Name:\s*(.+)$", profile.read_text(encoding="utf-8"), re.M)
        git(root, "config", "user.name", m.group(1).strip() if m else "Archive owner", check=True)
        git(root, "config", "user.email", "archive@localhost", check=True)
    git(root, "add", "-A", check=True)
    if git(root, "status", "--porcelain"):
        git(root, "commit", "-q", "-m", "Set up archive", check=True)

    print("Archive set up.")
    if created:
        print("Created: " + ", ".join(created))
    if removed:
        print("Removed git remotes (this repository stays local): " + ", ".join(removed))
    print("Next: fill STATE.md, then checkpoint.")
    return 0
