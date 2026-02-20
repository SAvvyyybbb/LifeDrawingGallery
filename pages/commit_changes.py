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

def git_push():
    """Push commits to the remote repository"""
    code, out, err = run_git(["push"])
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

    # Get all tables
    try:
        c.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in c.fetchall()]
    except Exception:
        tables = []

    # Load previous snapshot
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
FOLDER_SNAPSHOT_FILE = REPO_DIR / ".folder_snapshot.txt"

def get_folder_changes():
    current_folders = {}
    for folder in REPO_DIR.iterdir():
        if folder.is_dir():
            imgs = [p for p in folder.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
            current_folders[folder.name] = imgs

    previous_folders = {}
    if FOLDER_SNAPSHOT_FILE.exists():
        with open(FOLDER_SNAPSHOT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                name, files = line.strip().split("|")
                previous_folders[name] = files.split(",")

    added = {k: v for k, v in current_folders.items() if k not in previous_folders}
    removed = {k: v for k, v in previous_folders.items() if k not in current_folders}
    modified = {}
    for k in current_folders:
        if k in previous_folders:
            old_files = set(previous_folders[k])
            new_files = set(str(p.relative_to(REPO_DIR)) for p in current_folders[k])
            if old_files != new_files:
                modified[k] = {"added": new_files - old_files, "removed": old_files - new_files}

    # Update snapshot
    with open(FOLDER_SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        for name, files in current_folders.items():
            files_rel = [str(p.relative_to(REPO_DIR)) for p in files]
            f.write(f"{name}|{','.join(files_rel)}\n")

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
        if any(path.startswith(p) for p in IGNORED_PATTERNS) or "__pycache__" in path:
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

# ---------------- Folder Changes ----------------
st.markdown("---")
st.subheader("Image Processing Folder Changes")
added, removed, modified = get_folder_changes()

if not added and not removed and not modified:
    st.success("No folder/image changes detected.")
else:
    if added:
        with st.expander(f"New Folders ({len(added)})"):
            for f, files in added.items():
                st.write(f"**{f}** ({len(files)} images)")
                for file in files:
                    st.text(file)
    if removed:
        with st.expander(f"Removed Folders ({len(removed)})"):
            for f, files in removed.items():
                st.write(f"**{f}** ({len(files)} images)")
                for file in files:
                    st.text(file)
    if modified:
        with st.expander(f"Modified Folders ({len(modified)})"):
            for f, changes_dict in modified.items():
                st.write(f"**{f}**")
                if changes_dict.get("added"):
                    st.markdown(f"➕ Added ({len(changes_dict['added'])}):")
                    for file in changes_dict['added']:
                        st.text(file)
                if changes_dict.get("removed"):
                    st.markdown(f"➖ Removed ({len(changes_dict['removed'])}):")
                    for file in changes_dict['removed']:
                        st.text(file)

# ---------------- Commit & Push Changes ----------------
st.markdown("---")
st.subheader("Commit & Push Changes")
commit_msg = st.text_input("Commit message", value="Commit via Streamlit")
if st.button("Commit & Push Changes"):
    code, out, err = git_commit(commit_msg)
    if code == 0:
        st.success("Changes committed locally ✅")
        st.info(out)
        push_code, push_out, push_err = git_push()
        if push_code == 0:
            st.success("Changes pushed to GitHub ✅")
        else:
            st.error(f"Push failed: {push_err}")
    else:
        st.error(f"Commit failed: {err}")