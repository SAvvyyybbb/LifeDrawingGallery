# pages/commit_changes.py
import sys
import streamlit as st
from pathlib import Path
import sqlite3
import subprocess
import config
import time
import hashlib

# ---------------- Add modules folder to path ----------------
MODULES_DIR = Path(__file__).parent / "modules"
if MODULES_DIR.exists() and str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="UV Map Commit & Tracker",
    layout="wide"
)

# ---------------- Helper Functions ----------------
def run_git(args, repo_dir=config.IMAGE_PROCESSING_DIR):
    """Run a git command restricted to IMAGE_PROCESSING_DIR."""
    result = subprocess.run(
        ["git"] + args,
        cwd=repo_dir,
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def row_hash(row):
    """Generate a hash of a database row (ignoring id and batch_id)."""
    vals = [str(row[k]) for k in row.keys() if k not in ("id", "batch_id")]
    return hashlib.md5("|".join(vals).encode("utf-8")).hexdigest()

def get_db_changes():
    """Detect added/modified/removed rows in the main DB tables."""
    DB_PATH = config.DB_PATH
    if not DB_PATH.exists():
        return {"added": {}, "modified": {}, "removed": {}}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Only consider tables we know
    tables = ["images", "batches"]
    changes = {"added": {}, "modified": {}, "removed": {}}

    snapshot_file = DB_PATH.parent / ".db_snapshot.txt"
    previous_snapshot = {}

    if snapshot_file.exists():
        with open(snapshot_file, "r", encoding="utf-8") as f:
            for line in f:
                table_name, rowid, rhash = line.strip().split("|")
                previous_snapshot.setdefault(table_name, {})[int(rowid)] = rhash

    for table in tables:
        try:
            rows = c.execute(f"SELECT * FROM {table}").fetchall()
        except sqlite3.OperationalError:
            # Table does not exist
            continue

        current = {r["id"]: row_hash(r) for r in rows}

        prev_rows = previous_snapshot.get(table, {})

        added = {rid: h for rid, h in current.items() if rid not in prev_rows}
        removed = {rid: h for rid, h in prev_rows.items() if rid not in current}
        modified = {rid: h for rid, h in current.items() if rid in prev_rows and prev_rows[rid] != h}

        changes["added"][table] = added
        changes["removed"][table] = removed
        changes["modified"][table] = modified

    conn.close()

    # Update snapshot file
    with open(snapshot_file, "w", encoding="utf-8") as f:
        for table in tables:
            for rid, rhash in current.items():
                f.write(f"{table}|{rid}|{rhash}\n")

    return changes

# ---------------- Landing Content ----------------
st.title("Commit Changes & Tracker Dashboard")
st.write("""
Monitor repository, database, and image processing folder changes.
You can review changes and commit directly from this page.
""")

st.markdown("---")

# ---------------- Git Repository Status ----------------
st.subheader("Git Repository Status (Restricted to Image Processing Folder)")

if st.button("Check Repository Status"):
    code, out, err = run_git(["status", "--porcelain"])
    if code != 0:
        st.error(f"Git error: {err}")
    else:
        lines = out.splitlines()
        st.write(f"Detected {len(lines)} local changes:")
        if lines:
            with st.expander("Local Changes", expanded=True):
                for line in lines:
                    st.write(f"- {line}")
        else:
            st.success("No local changes detected.")

st.divider()

# ---------------- Database Changes ----------------
st.subheader("Database Changes")

db_changes = get_db_changes()
if not any(db_changes.values()):
    st.success("No database changes detected.")
else:
    for change_type in ["added", "modified", "removed"]:
        total = sum(len(v) for v in db_changes[change_type].values())
        if total:
            with st.expander(f"{change_type.capitalize()} rows ({total})", expanded=False):
                for table, rows in db_changes[change_type].items():
                    if rows:
                        st.write(f"**Table: {table}**")
                        for rid in rows:
                            st.write(f"- Row ID: {rid}")

st.divider()

# ---------------- Folder & Image Tracker ----------------
st.subheader("Image Processing Folder Tracker")

ROOT_TRACK_DIR = config.IMAGE_PROCESSING_DIR
if ROOT_TRACK_DIR.exists():
    # Map current folders and images recursively
    current_folders = [p for p in ROOT_TRACK_DIR.rglob("*") if p.is_dir()]
    folder_summary = []

    for folder in current_folders:
        images = sorted([p for p in folder.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg")])
        folder_summary.append({
            "folder": str(folder.relative_to(ROOT_TRACK_DIR)),
            "image_count": len(images),
            "image_paths": images
        })

    # Compare with previous snapshot
    snapshot_file = ROOT_TRACK_DIR / ".folder_snapshot.txt"
    previous_snapshot = {}
    if snapshot_file.exists():
        with open(snapshot_file, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) == 2:
                    prev_folder, prev_count = parts
                    previous_snapshot[prev_folder] = int(prev_count)

    new_folders = []
    deleted_folders = []
    modified_folders = []

    for f in folder_summary:
        name = f["folder"]
        count = f["image_count"]
        prev_count = previous_snapshot.get(name)
        if prev_count is None:
            new_folders.append((name, count))
        elif prev_count != count:
            modified_folders.append((name, prev_count, count))

    for prev_name in previous_snapshot:
        if prev_name not in [f["folder"] for f in folder_summary]:
            deleted_folders.append(prev_name)

    # Display results
    if new_folders:
        with st.expander(f"New Folders ({len(new_folders)})", expanded=True):
            for name, count in new_folders:
                st.write(f"- {name}: {count} images")

    if modified_folders:
        with st.expander(f"Modified Folders ({len(modified_folders)})", expanded=False):
            for name, prev_count, count in modified_folders:
                st.write(f"- {name}: {prev_count} → {count} images")

    if deleted_folders:
        with st.expander(f"Deleted Folders ({len(deleted_folders)})", expanded=False):
            for name in deleted_folders:
                st.write(f"- {name}")

    if not (new_folders or modified_folders or deleted_folders):
        st.success("No folder changes detected.")

    # Update snapshot for next run
    with open(snapshot_file, "w", encoding="utf-8") as f:
        for fsum in folder_summary:
            f.write(f"{fsum['folder']}|{fsum['image_count']}\n")
else:
    st.warning(f"Image Processing folder not found: {ROOT_TRACK_DIR}")

st.divider()

# ---------------- Commit Button ----------------
st.subheader("Commit Changes")

commit_message = st.text_input("Commit message:", value="Update changes from Streamlit dashboard")
if st.button("Commit & Push Changes"):
    # Stage all changes in IMAGE_PROCESSING_DIR
    code, out, err = run_git(["add", "."], repo_dir=config.IMAGE_PROCESSING_DIR)
    if code != 0:
        st.error(f"Git add failed: {err}")
    else:
        code, out, err = run_git(["commit", "-m", commit_message], repo_dir=config.IMAGE_PROCESSING_DIR)
        if code != 0:
            st.warning(f"Commit may have failed (nothing to commit?): {err}")
        else:
            st.success("Changes committed successfully.")
            st.info(out)
            # Push
            code, out, err = run_git(["push"], repo_dir=config.IMAGE_PROCESSING_DIR)
            if code != 0:
                st.error(f"Push failed: {err}")
            else:
                st.success("Changes pushed to remote successfully.")