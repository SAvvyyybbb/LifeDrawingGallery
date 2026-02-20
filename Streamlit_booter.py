# pages/dashboard.py
import sys
import streamlit as st
from pathlib import Path
from PIL import Image, ImageOps
import time
import config
import subprocess

# ---------------- Add modules folder to path ----------------
MODULES_DIR = Path(__file__).parent / "pages" / "modules"
if MODULES_DIR.exists() and str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))

try:
    from folder_preview import folder_preview_panel  # optional module
except ImportError:
    folder_preview_panel = None

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

# Run pull only once per session
if "git_synced" not in st.session_state:
    code, out, err = run_git(["pull", "--rebase"])
    st.session_state.git_synced = True  # mark as done

    if code == 0:
        st.success("Repository inside Image Processing folder is up to date ✅")
        if out:
            st.info(f"Git output:\n{out}")
    else:
        st.error("Failed to pull updates ⚠️")
        if err:
            st.error(f"Git error:\n{err}")
        st.warning("Resolve conflicts manually before continuing.")
else:
    st.info("Repository sync already performed this session.")

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
CLEANED_DIR.mkdir(parents=True, exist_ok=True)  # <-- ensure folder exists

# Collect images
cleaned_images = sorted([
    p for p in CLEANED_DIR.iterdir()
    if p.suffix.lower() in (".png", ".jpg", ".jpeg")
])

total_images = len(cleaned_images)
st.write(f"**Total Images in folder:** {total_images}")

# Recently modified images (last 7 days)
recent_threshold = time.time() - 7*24*60*60
recent_images = [p for p in cleaned_images if p.stat().st_mtime >= recent_threshold]
st.write(f"**Recently added/modified (last 7 days):** {len(recent_images)}")

# ---------------- Thumbnail Grid ----------------
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
            try:
                with Image.open(img_path) as im:
                    thumb = ImageOps.exif_transpose(im).convert("RGB")
                    thumb.thumbnail((thumb_size, thumb_size))
                border_color = "#FF0000" if img_path in recent_images else "#CCCCCC"
                cols[c].image(thumb, width=thumb_size, caption=img_path.name, use_column_width=False)
            except Exception as e:
                st.warning(f"Failed to load thumbnail: {img_path.name} ({e})")