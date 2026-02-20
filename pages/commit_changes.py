# pages/commit_changes.py
import streamlit as st
import subprocess
from pathlib import Path
import sqlite3
import hashlib
import json
import config

REPO_DIR = Path(__file__).resolve().parents[1]  # assumes repo root


# ---------- Git Helpers ----------
def run_git(args):
    result = subprocess.run(
        ["git"] + args,
        cwd=REPO_DIR,
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def get_status():
    code, out, err = run_git(["status", "--porcelain"])
    if code != 0:
        return None, err
    return out.splitlines(), None


def get_diff():
    code, out, err = run_git(["diff"])
    if code != 0:
        return None
    return out


def commit_and_push(message):
    run_git(["add", "."])
    code, out, err = run_git(["commit", "-m", message])
    if code != 0:
        return False, err or out
    code, out, err = run_git(["push"])
    if code != 0:
        return False, err or out
    return True, "Commit + push successful"


# ---------- Database Helpers ----------
def row_hash(row):
    return hashlib.sha1(json.dumps(dict(row), sort_keys=True).encode()).hexdigest()


def get_db_changes():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Ensure snapshot table exists
    c.execute("""
        CREATE TABLE IF NOT EXISTS _audit_snapshot (
            table_name TEXT,
            row_id INTEGER,
            hash TEXT
        )
    """)

    tables = ["images", "batches"]
    changes = {"added": [], "modified": [], "removed": []}

    for table in tables:
        rows = c.execute(f"SELECT * FROM {table}").fetchall()
        current = {r["id"]: row_hash(r) for r in rows}

        snap_rows = c.execute(
            "SELECT row_id, hash FROM _audit_snapshot WHERE table_name=?",
            (table,)
        ).fetchall()
        snapshot = {r[0]: r[1] for r in snap_rows}

        # Detect added/modified rows
        for rid, h in current.items():
            if rid not in snapshot:
                changes["added"].append((table, rid))
            elif snapshot[rid] != h:
                changes["modified"].append((table, rid))

        # Detect removed rows
        for rid in snapshot:
            if rid not in current:
                changes["removed"].append((table, rid))

        # Update snapshot
        c.execute("DELETE FROM _audit_snapshot WHERE table_name=?", (table,))
        c.executemany(
            "INSERT INTO _audit_snapshot VALUES (?,?,?)",
            [(table, rid, h) for rid, h in current.items()]
        )

    conn.commit()
    conn.close()
    return changes


# ---------- Streamlit UI ----------
st.title("Repository Commit & Database Change Panel")

# --- Git Status ---
status, err = get_status()
if err:
    st.error(f"Git error: {err}")
    st.stop()

if not status:
    st.success("Working tree clean — no changes detected.")
else:
    st.subheader("Detected Git Changes")
    added, modified, deleted = [], [], []

    for line in status:
        flag = line[:2]
        file = line[3:]
        if "A" in flag:
            added.append(file)
        elif "M" in flag:
            modified.append(file)
        elif "D" in flag:
            deleted.append(file)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Added Files**")
        st.write(added or "-")
    with col2:
        st.markdown("**Modified Files**")
        st.write(modified or "-")
    with col3:
        st.markdown("**Deleted Files**")
        st.write(deleted or "-")

    st.subheader("Diff Preview")
    diff = get_diff()
    if diff:
        st.code(diff, language="diff")
    else:
        st.info("No textual diff available (possibly binary files).")

# --- Database Changes ---
st.divider()
st.subheader("Database Changes")

db_changes = get_db_changes()
if not any(db_changes.values()):
    st.success("No database changes detected.")
else:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Added Rows**")
        st.write(db_changes["added"] or "-")
    with col2:
        st.markdown("**Modified Rows**")
        st.write(db_changes["modified"] or "-")
    with col3:
        st.markdown("**Removed Rows**")
        st.write(db_changes["removed"] or "-")

# --- Commit Section ---
st.divider()
st.subheader("Finalize Commit")

commit_msg = st.text_input("Commit message")

confirm = st.checkbox("I confirm I want to commit these changes")

if st.button("Commit & Push") and confirm:
    if not commit_msg.strip():
        st.warning("Enter a commit message first.")
        st.stop()

    success, result = commit_and_push(commit_msg)
    if success:
        st.success(result)
        st.experimental_rerun()
    else:
        st.error(result)