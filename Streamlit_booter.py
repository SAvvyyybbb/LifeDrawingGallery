# pages/dashboard.py
import sys
import streamlit as st
from pathlib import Path
from PIL import Image, ImageOps
import time
import sqlite3
import config
import subprocess

# ---------------- Add modules folder to path ----------------
MODULES_DIR = Path(__file__).parent / "pages" / "modules"
if MODULES_DIR.exists() and str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))

from folder_preview import folder_preview_panel  # optional module

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="UV Map Stitcher Dashboard",
    layout="wide"
)

# ---------------- Git Auto-Pull restricted to IMAGE_PROCESSING_DIR ----------------
REPO_DIR = config.IMAGE_PROCESSING_DIR.resolve()

def run_git(args):
    result = subprocess.run(
        ["git"] + args,
        cwd=REPO_DIR,
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()

st.subheader("Repository Sync Status (Restricted)")

code, out, err = run_git(["pull", "--rebase"])
if code == 0:
    st.success("Repository inside Image Processing folder is up to date ✅")
    if out:
        st.info(f"Git output:\n{out}")
else:
    st.error("Failed to pull updates ⚠️")
    if err:
        st.error(f"Git error:\n{err}")
    st.warning("Resolve conflicts manually before continuing.")

# ---------------- Landing Content ----------------
st.title("UV Map Stitcher Dashboard")
st.write("""
Welcome to the LifeDrawingGallery UV Map Stitcher!

This dashboard helps you manage the workflow from raw/cleaned images to batch creation, stitching, and gallery audit.
""")

st.markdown("---")

st.subheader("Stage 0: Preprocess Raw Images (Optional)")
st.write("""
**Purpose:** Stage 0 is an optional preprocessing step for your raw images before ingestion.
""")

st.markdown("---")
st.info("Select a stage from the sidebar or top menu to begin your workflow.")

# ---------------- Folder Preview ----------------
st.subheader("Cleaned Images Preview")
CLEANED_DIR = config.CLEANED_DIR
cleaned_images = sorted([p for p in CLEANED_DIR.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")])

total_images = len(cleaned_images)
st.write(f"**Total Images in folder:** {total_images}")

recent_threshold = time.time() - 7*24*60*60
recent_images = [p for p in cleaned_images if p.stat().st_mtime >= recent_threshold]
st.write(f"**Recently added/modified (last 7 days):** {len(recent_images)}")

# Thumbnail Grid
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

# ---------------- Database Explorer ----------------
st.markdown("---")
st.subheader("Database Explorer (Optional)")
db_root = config.DB_DIR
if db_root.exists():
    show_db_explorer = st.checkbox("Show Database Explorer", value=False)
    if show_db_explorer:
        db_files = sorted([p for p in db_root.iterdir() if p.suffix == ".db"])
        if db_files:
            st.write(f"Found **{len(db_files)}** database files:")
            for db_file in db_files:
                file_stat = db_file.stat()
                modified_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(file_stat.st_mtime))
                size_kb = file_stat.st_size / 1024
                st.markdown(f"- **{db_file.name}** — {size_kb:.1f} KB — last modified {modified_time}")
                if st.button(f"Show Tables in {db_file.name}", key=db_file.name):
                    try:
                        conn = sqlite3.connect(db_file)
                        cursor = conn.cursor()
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                        tables = cursor.fetchall()
                        conn.close()
                        if tables:
                            table_list = [t[0] for t in tables]
                            st.write(f"Tables: {', '.join(table_list)}")
                        else:
                            st.write("No tables found.")
                    except Exception as e:
                        st.error(f"Error reading {db_file.name}: {e}")
else:
    st.warning(f"Database folder not found: {db_root}")