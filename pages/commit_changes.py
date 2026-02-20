# pages/commit_changes.py
import sys
import streamlit as st
from pathlib import Path
from PIL import Image, ImageOps
import sqlite3
import hashlib
import time
import subprocess
import config

# ---------------- Add modules folder to path ----------------
MODULES_DIR = Path(__file__).parent / "modules"
if MODULES_DIR.exists() and str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))

# Optional module
try:
    from folder_preview import folder_preview_panel
except ImportError:
    folder_preview_panel = None

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="Check & Commit Changes",
    layout="wide"
)

st.title("Check & Commit Changes")
st.write("This page lets you inspect local tracked changes, view database differences, and commit updates manually.")

st.markdown("---")

# ---------------- Git: Check & Commit ----------------
REPO_DIR = config.IMAGE_PROCESSING_DIR.resolve()

def run_git(args):
    """Run git command inside IMAGE_PROCESSING_DIR"""
    result = subprocess.run(
        ["git"] + args,
        cwd=REPO_DIR,
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def get_tracked_changes():
    """Return only tracked changes, ignoring untracked files/folders."""
    code, out, err = run_git(["status", "--porcelain"])
    if code != 0:
        st.error(f"Git status error: {err}")
        return []

    # Filter out untracked files (lines starting with '??')
    tracked_lines = [line for line in out.splitlines() if not line.startswith("??")]
    return tracked_lines

st.subheader("Git Repository Status & Commit")

# --- Check Status Button ---
if st.button("Check Repository Status"):
    tracked_changes = get_tracked_changes()
    if not tracked_changes:
        st.success("No local tracked changes detected.")
    else:
        st.warning(f"Detected {len(tracked_changes)} local tracked changes:")
        for line in tracked_changes:
            st.write(f"- {line}")

# --- Commit Changes Button ---
commit_msg = st.text_input("Commit message for changes:", value="Update from Streamlit dashboard")
if st.button("Commit Changes"):
    code, out, err = run_git(["add", "."])
    if code != 0:
        st.error(f"Git add failed: {err}")
    else:
        st.info("Staged all changes.")
        code, out, err = run_git(["commit", "-m", commit_msg])
        if code != 0:
            if "nothing to commit" in err.lower():
                st.warning("Nothing to commit.")
            else:
                st.error(f"Git commit failed: {err}")
        else:
            st.success("Changes committed successfully.")
            st.info(out)

st.markdown("---")

# ---------------- Database Changes ----------------
st.subheader("Database Changes")

def get_db_changes():
    """Detect rows added per table (counts actual rows)."""
    changes = {"added": [], "modified": [], "removed": []}
    db_files = sorted([p for p in config.DB_DIR.iterdir() if p.suffix == ".db"])
    for db_file in db_files:
        try:
            conn = sqlite3.connect(db_file)
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [t[0] for t in c.fetchall()]
            for table in tables:
                try:
                    # Count actual rows
                    row_count = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    if row_count > 0:
                        changes["added"].append(f"{db_file.name}/{table}: {row_count} rows")
                except sqlite3.OperationalError:
                    continue
            conn.close()
        except Exception as e:
            st.error(f"Error reading {db_file.name}: {e}")
    return changes

db_changes = get_db_changes()
if not any(db_changes.values()):
    st.success("No database changes detected.")
else:
    st.warning("Database changes detected:")
    for change_type, items in db_changes.items():
        if items:
            st.write(f"**{change_type.capitalize()} ({len(items)} tables)**")
            for i in items:
                st.write(f"- {i}")

st.markdown("---")

# ---------------- Cleaned Images Preview ----------------
st.subheader("Cleaned Images Preview")
CLEANED_DIR = config.CLEANED_DIR
if CLEANED_DIR.exists():
    cleaned_images = sorted([p for p in CLEANED_DIR.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")])
    total_images = len(cleaned_images)
    st.write(f"**Total Images:** {total_images}")

    recent_threshold = time.time() - 7*24*60*60
    recent_images = [p for p in cleaned_images if p.stat().st_mtime >= recent_threshold]

    thumb_cols = 6
    thumb_size = 120
    if total_images == 0:
        st.info("No images found in the cleaned folder.")
    else:
        rows = (total_images + thumb_cols - 1) // thumb_cols
        for r in range(rows):
            cols = st.columns(thumb_cols)
            for c in range(thumb_cols):
                idx = r * thumb_cols + c
                if idx >= total_images:
                    break
                img_path = cleaned_images[idx]
                with Image.open(img_path) as im:
                    thumb = ImageOps.exif_transpose(im).convert("RGB")
                    thumb.thumbnail((thumb_size, thumb_size))
                border_color = "#FF0000" if img_path in recent_images else "#CCCCCC"
                cols[c].image(thumb, width=thumb_size, caption=img_path.name, use_column_width=False)
else:
    st.warning(f"Cleaned images folder not found: {CLEANED_DIR}")