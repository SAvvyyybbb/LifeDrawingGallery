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

# ---------------- Git Helpers ----------------
REPO_DIR = config.IMAGE_PROCESSING_DIR.resolve()

def run_git(args):
    result = subprocess.run(
        ["git"] + args,
        cwd=REPO_DIR,
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()

def get_local_modified_files():
    """Return a set of relative paths for locally modified/uncommitted files"""
    code, out, err = run_git(["status", "--porcelain"])
    modified_files = set()
    if code == 0 and out.strip():
        for line in out.strip().splitlines():
            status, path = line[:2].strip(), line[3:]
            if status in {"M", "A", "??"}:
                modified_files.add(path.replace("\\","/"))
    return modified_files

def undo_all_changes():
    """Reset all local changes in the repo"""
    run_git(["reset", "--hard"])
    run_git(["clean", "-fd"])
    st.success("All local changes discarded ✅")

def git_pull(show_files=True):
    """Pull latest changes from GitHub and optionally display changed files"""
    code, out, err = run_git(["pull", "--rebase"])
    if code == 0:
        st.success("Repository is up to date ✅")
        if out:
            st.info(f"Git output:\n{out}")
        if show_files:
            code_files, out_files, err_files = run_git(["diff", "--name-status", "HEAD@{1}", "HEAD"])
            if code_files == 0 and out_files.strip():
                changed = out_files.strip().splitlines()
                st.subheader("Files Changed in Last Pull")
                for line in changed:
                    status, file_path = line.split("\t", 1)
                    status_emoji = {"A":"➕","M":"✏️","D":"➖"}.get(status, status)
                    st.write(f"{status_emoji} {file_path}")
            else:
                st.info("No files changed in this pull.")
        return True

    # Pull failed — likely due to local changes
    st.error("Failed to pull updates ⚠️")
    if err:
        st.error(f"Git error:\n{err}")
    st.warning("Resolve conflicts manually before continuing.")

    # Two-step confirmation for discarding changes
    if "confirm_uncommit" not in st.session_state:
        if st.button("Discard All Local Changes"):
            st.session_state.confirm_uncommit = True
    elif st.session_state.confirm_uncommit:
        st.warning("Are you sure? This will undo any changes you've made in this session.")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Yes, Discard Changes"):
                undo_all_changes()
                st.session_state.confirm_uncommit = False
                git_pull()  # retry pull
        with col2:
            if st.button("Cancel"):
                st.session_state.confirm_uncommit = False

    return False

# ---------------- Git Pull Button ----------------
st.subheader("Repository Sync Status (Restricted)")
if st.button("Pull Latest Changes"):
    git_pull()
elif "git_synced" not in st.session_state:
    git_pull()
    st.session_state.git_synced = True
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
CLEANED_DIR.mkdir(parents=True, exist_ok=True)

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

# Local modified/uncommitted files
local_modified_files = get_local_modified_files()

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

                # Determine border color
                img_rel_path = str(img_path.relative_to(REPO_DIR)).replace("\\","/")
                if img_path in recent_images:
                    border_color = "#FF0000"  # recent
                elif img_rel_path in local_modified_files:
                    border_color = "#FFA500"  # modified/uncommitted
                else:
                    border_color = "#CCCCCC"  # unchanged

                # Draw border
                bordered_thumb = Image.new("RGB", (thumb_size, thumb_size), border_color)
                bordered_thumb.paste(thumb, ((thumb_size - thumb.width)//2, (thumb_size - thumb.height)//2))

                cols[c].image(
                    bordered_thumb,
                    width=thumb_size,
                    caption=img_path.name,
                    use_column_width=False
                )
            except Exception as e:
                st.warning(f"Failed to load thumbnail: {img_path.name} ({e})")