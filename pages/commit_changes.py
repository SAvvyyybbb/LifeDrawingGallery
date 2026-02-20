# pages/dashboard.py
import sys
import streamlit as st
from pathlib import Path
from PIL import Image, ImageOps
import time
import sqlite3
import subprocess
import config

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

# ---------------- Git Auto-Pull with Auto-Stash ----------------
REPO_DIR = config.IMAGE_PROCESSING_DIR.resolve()

def run_git(args):
    result = subprocess.run(
        ["git"] + args,
        cwd=REPO_DIR,
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()

st.subheader("Repository Auto-Sync Status (Restricted)")

# Check for uncommitted changes
status_code, status_out, status_err = run_git(["status", "--porcelain"])
if status_code != 0:
    st.error(f"Git status error: {status_err}")
else:
    st.info(f"Detected {len(status_out.splitlines())} local changes.")

    stash_applied = False
    if status_out:
        # Stash local changes (including untracked)
        code, out, err = run_git(["stash", "push", "-u", "-m", "streamlit-autostash"])
        if code == 0:
            st.info("Local changes stashed before pull.")
            stash_applied = True
        else:
            st.warning(f"Failed to stash local changes: {err}")

    # Pull latest changes with rebase
    code, out, err = run_git(["pull", "--rebase"])
    if code == 0:
        st.success("Repository updated successfully inside Image Processing folder ✅")
        if out:
            st.info(out)
    else:
        st.error(f"Pull failed: {err}")

    # Re-apply stash if needed
    if stash_applied:
        code, out, err = run_git(["stash", "pop"])
        if code == 0:
            st.success("Local changes restored from stash.")
            if out:
                st.info(out)
        else:
            st.warning(f"Failed to apply stashed changes automatically: {err}")

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
Recommended if your images have black borders, inconsistent aspect ratios, or require resizing.

**What Stage 0 does:**
1. Scans your `Raw` folder for image files (`.png`, `.jpg`, `.jpeg`).
2. Converts all images to RGB if they contain an alpha channel (transparency).
3. Removes black borders based on a tolerance threshold.
4. Crops and classifies images by aspect ratio.
5. Resizes images to standard dimensions per category.
6. Saves the processed images to the `2_Cleaned` folder.
7. Optionally deletes the original raw images after processing.

**Why run this step:**  
- Ensures consistency for Stage 1 ingestion and batching.  
- Removes unnecessary black borders.  
- Standardizes image dimensions for layout and UV stitching.  
""")

st.markdown("---")

st.subheader("Workflow Overview")
st.write("""
1. **Stage 0: Preprocess Raw Images** (optional)  
2. **Stage 1: Ingestion Scan** – scan cleaned images and create batches.  
3. **Stage 2: Batch Layout & Manual Ordering** – adjust image order and preview batches.  
4. **Stage 3: UV Map Stitching** – generate UV maps and export images.  
5. **Stage 4: Gallery Audit** – review and verify all stitched images.

Use the sidebar or top menu to navigate to each stage when ready.  
This landing page does **not execute any processing**, it is purely informational.
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