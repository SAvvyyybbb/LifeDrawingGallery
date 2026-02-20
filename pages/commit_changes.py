# pages/commit_changes.py
import sys
import streamlit as st
from pathlib import Path
import subprocess
import sqlite3
import config
import hashlib

# ---------------- Add modules folder to path ----------------
MODULES_DIR = Path(__file__).parent / "modules"
if MODULES_DIR.exists() and str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="Repository Commit & DB Tracker",
    layout="wide"
)

# ---------------- Git Helpers ----------------
REPO_DIR = config.IMAGE_PROCESSING_DIR.resolve()

def run_git(args):
    """Run git commands restricted to IMAGE_PROCESSING_DIR"""
    result = subprocess.run(
        ["git"] + args,
        cwd=REPO_DIR,
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def git_status():
    code, out, err = run_git(["status", "--porcelain"])
    if code != 0:
        return [], err
    lines = out.splitlines()
    return lines, None

def git_commit(message="Commit via Streamlit"):
    """Stage all changes and commit with a local Git identity"""
    # Stage all changes
    run_git(["add", "."])

    # Set local user identity (repo-specific)
    run_git(["config", "user.name", "Streamlit Bot"])
    run_git(["config", "user.email", "bot@example.com"])

    # Commit changes
    code, out, err = run_git(["commit", "-m", message])
    return code, out, err

# ---------------- DB Change Tracker ----------------
SNAPSHOT_FILE = REPO_DIR / ".db_snapshot.txt"

def row_hash(row):
    """Compute a hash for a DB row (ignores internal ordering)"""
    return hashlib.md5(str(tuple(row)).encode("utf-8")).hexdigest()

def get_db_changes():
    changes = {"added": {}, "modified": {}, "removed": {}}
    db_path = config.DB_PATH
    if not db_path.exists():
        return changes

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    try:
        c.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in c.fetchall()]
    except Exception:
        tables = []

    previous_snapshot = {}
    if SNAPSHOT_FILE.exists():
        with open(SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                table, rid, rhash = line.strip().split("|")
                previous_snapshot.setdefault(table, {})[int(rid)] = rhash

    new_snapshot_lines = []

    for table in tables:
        current = {}
        try:
            rows = c.execute(f"SELECT * FROM {table}").fetchall()
            if rows and "id" in rows[0].keys():
                current = {r["id"]: row_hash(r) for r in rows}
            else:
                rows = c.execute(f"SELECT rowid, * FROM {table}").fetchall()
                current = {r["rowid"]: row_hash(r) for r in rows}
        except sqlite3.OperationalError:
            continue

        prev_rows = previous_snapshot.get(table, {})

        added = {rid: h for rid, h in current.items() if rid not in prev_rows}
        removed = {rid: h for rid, h in prev_rows.items() if rid not in current}
        modified = {rid: h for rid, h in current.items() if rid in prev_rows and prev_rows[rid] != h}

        if added:
            changes["added"][table] = added
        if removed:
            changes["removed"][table] = removed
        if modified:
            changes["modified"][table] = modified

        for rid, rhash in current.items():
            new_snapshot_lines.append(f"{table}|{rid}|{rhash}")

    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        for line in new_snapshot_lines:
            f.write(line + "\n")

    conn.close()
    return changes

# ---------------- Folder Tracker ----------------
def get_folder_changes():
    IMAGE_DIR = config.IMAGE_PROCESSING_DIR
    snapshot_file = IMAGE_DIR / ".folder_snapshot.txt"

    current_folders = {}
    for folder in IMAGE_DIR.iterdir():
        if folder.is_dir():
            imgs = [p for p in folder.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
            current_folders[folder.name] = len(imgs)

    previous_folders = {}
    if snapshot_file.exists():
        with open(snapshot_file, "r", encoding="utf-8") as f:
            for line in f:
                name, count = line.strip().split("|")
                previous_folders[name] = int(count)

    added = {k: v for k, v in current_folders.items() if k not in previous_folders}
    removed = {k: v for k, v in previous_folders.items() if k not in current_folders}
    modified = {k: (previous_folders[k], current_folders[k])
                for k in current_folders if k in previous_folders and previous_folders[k] != current_folders[k]}

    with open(snapshot_file, "w", encoding="utf-8") as f:
        for name, count in current_folders.items():
            f.write(f"{name}|{count}\n")

    return added, removed, modified

# ---------------- UI ----------------
st.title("Repository Commit & Database Tracker")

# ---------------- Git Status ----------------
st.subheader("Check Repository Status")
IGNORED_PATTERNS = [".streamlit/"]

def filter_git_status(lines):
    filtered = []
    for line in lines:
        path = line[3:] if len(line) > 3 else line
        if path.startswith(".streamlit/") or "__pycache__" in path:
            continue
        filtered.append(line)
    return filtered

if st.button("Check Repository Status"):
    lines, err = git_status()
    if err:
        st.error(f"Git error: {err}")
    else:
        lines = filter_git_status(lines)
        if not lines:
            st.success("No tracked changes detected ✅")
        else:
            st.info(f"Detected {len(lines)} local changes:")
            for l in lines:
                st.text(l)

# ---------------- Database Changes ----------------
st.markdown("---")
st.subheader("Database Changes")
db_changes = get_db_changes()
if not any(db_changes.values()):
    st.success("No database changes detected.")
else:
    for change_type, tables in db_changes.items():
        with st.expander(f"{change_type.capitalize()} ({sum(len(v) for v in tables.values())} rows)"):
            for table, rows in tables.items():
                st.write(f"**Table {table}:** {len(rows)} rows")
                st.text(", ".join(str(rid) for rid in rows))

# ---------------- Folder Tracker ----------------
st.markdown("---")
st.subheader("Image Processing Folder Tracker")
added, removed, modified = get_folder_changes()
if not added and not removed and not modified:
    st.success("No folder or image count changes detected.")
else:
    if added:
        with st.expander(f"New Folders ({len(added)})"):
            for f, c in added.items():
                st.write(f"{f}: {c} images")
    if removed:
        with st.expander(f"Removed Folders ({len(removed)})"):
            for f, c in removed.items():
                st.write(f"{f}: {c} images")
    if modified:
        with st.expander(f"Modified Folders ({len(modified)})"):
            for f, counts in modified.items():
                st.write(f"{f}: {counts[0]} → {counts[1]} images")

# ---------------- Commit Changes ----------------
st.markdown("---")
st.subheader("Commit Changes to Repository")
commit_msg = st.text_input("Commit message", value="Commit via Streamlit")
if st.button("Commit Changes"):
    code, out, err = git_commit(commit_msg)
    if code == 0:
        st.success("Changes committed successfully ✅")
        if out:
            st.info(out)
    else:
        st.error(f"Commit failed: {err}")