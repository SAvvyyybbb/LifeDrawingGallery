import streamlit as st
from pathlib import Path
from PIL import Image
import shutil
import config

# ---------------- Config ----------------
ROOT_DIR = config.CLEANED_DIR  # Root for this manager
IMAGE_EXTS = (".png", ".jpg", ".jpeg")
THUMBNAIL_SIZE = 120
COLS_PER_ROW = 6

st.set_page_config(page_title="Folder Manager", layout="wide")

# ---------------- Helpers ----------------
def list_subfolders(path: Path):
    return sorted([p for p in path.iterdir() if p.is_dir()])

def list_images(path: Path):
    return sorted([p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTS])

def safe_image_open(path: Path):
    try:
        return Image.open(path)
    except:
        return None

def move_images(image_paths, target_folder: Path):
    target_folder.mkdir(parents=True, exist_ok=True)
    for img_path in image_paths:
        src = Path(img_path)
        if src.exists():
            shutil.move(str(src), str(target_folder / src.name))

def delete_images(image_paths):
    for img_path in image_paths:
        try:
            Path(img_path).unlink()
        except Exception as e:
            st.warning(f"Could not delete {img_path}: {e}")

# ---------------- Session State ----------------
if "current_folder" not in st.session_state:
    st.session_state.current_folder = ROOT_DIR
if "images_to_move" not in st.session_state:
    st.session_state.images_to_move = set()
if "refresh_counter" not in st.session_state:
    st.session_state.refresh_counter = 0

# ---------------- Sidebar ----------------
st.sidebar.header("Folder Navigation")

# Go up button
if st.sidebar.button("⬆ Go Up"):
    if st.session_state.current_folder != ROOT_DIR:
        st.session_state.current_folder = st.session_state.current_folder.parent
        st.session_state.images_to_move.clear()
        st.session_state.refresh_counter += 1

# Open folder selectbox
subfolders = list_subfolders(st.session_state.current_folder)
folder_names = ["./"] + [f.name for f in subfolders]
choice = st.sidebar.selectbox("Open Folder", folder_names)
if choice != "./":
    st.session_state.current_folder = st.session_state.current_folder / choice
    st.session_state.images_to_move.clear()
    st.session_state.refresh_counter += 1

# Create / delete folders
st.sidebar.markdown("---")
new_folder = st.sidebar.text_input("Create Folder / Subfolder")
if st.sidebar.button("Create"):
    if new_folder:
        (st.session_state.current_folder / new_folder).mkdir(parents=True, exist_ok=True)
        st.success(f"Created folder '{new_folder}'")
        st.session_state.refresh_counter += 1

# List empty folders for deletion
empty_folders = [f.name for f in list_subfolders(st.session_state.current_folder) if not any(f.iterdir())]
if empty_folders:
    del_choice = st.sidebar.selectbox("Delete Empty Folder", empty_folders)
    if st.sidebar.button("Delete Selected"):
        try:
            (st.session_state.current_folder / del_choice).rmdir()
            st.success(f"Deleted folder '{del_choice}'")
            st.session_state.refresh_counter += 1
        except:
            st.warning("Folder not empty or cannot delete")

# ---------------- Main Panel ----------------
st.title("Cleaned Folder Manager")
st.caption(f"📁 {st.session_state.current_folder.relative_to(ROOT_DIR)}")

# ---------------- Fetch images ----------------
all_images = list_images(st.session_state.current_folder)

# ---------------- Display Image Grid ----------------
rows = (len(all_images) + COLS_PER_ROW - 1) // COLS_PER_ROW
for r in range(rows):
    cols = st.columns(COLS_PER_ROW)
    for c in range(COLS_PER_ROW):
        idx = r * COLS_PER_ROW + c
        if idx >= len(all_images):
            continue
        img_path = all_images[idx]
        img = safe_image_open(img_path)
        if img is None:
            continue

        with cols[c]:
            st.image(img, width=THUMBNAIL_SIZE)
            key = f"chk_{img_path}_{st.session_state.refresh_counter}"  # refresh-aware key
            checked = st.checkbox(
                "",
                value=(str(img_path) in st.session_state.images_to_move),
                key=key
            )
            if checked:
                st.session_state.images_to_move.add(str(img_path))
            else:
                st.session_state.images_to_move.discard(str(img_path))

# ---------------- Move Selected Images ----------------
st.markdown("---")
st.subheader("Move Selected Images")

if st.session_state.images_to_move:
    # Determine top-level aspect folder (first part relative to CLEANED_DIR)
    rel_parts = st.session_state.current_folder.relative_to(ROOT_DIR).parts
    if len(rel_parts) == 0:
        st.info("Cannot move images from root folder.")
    else:
        # Top-level aspect folder
        main_aspect_folder = ROOT_DIR / rel_parts[0]
        # Only subfolders inside this aspect folder, excluding current folder
        eligible_folders = [f for f in list_subfolders(main_aspect_folder) if f != st.session_state.current_folder]

        if eligible_folders:
            destination = st.selectbox(
                "Move to folder",
                [f.name for f in eligible_folders],
                key=f"dest_select_{st.session_state.refresh_counter}"
            )
            if st.button("Move Images"):
                move_images(st.session_state.images_to_move, main_aspect_folder / destination)
                st.success(f"Moved {len(st.session_state.images_to_move)} images to '{destination}'")
                st.session_state.images_to_move.clear()
                st.session_state.refresh_counter += 1
        else:
            st.info("No eligible subfolders in this aspect category.")
else:
    st.info("No images selected for moving.")

# ---------------- Delete Selected Images ----------------
st.markdown("---")
st.subheader("Delete Selected Images")

if st.session_state.images_to_move:
    if st.button("Delete Images"):
        delete_images(st.session_state.images_to_move)
        st.success(f"Deleted {len(st.session_state.images_to_move)} images")
        st.session_state.images_to_move.clear()
        st.session_state.refresh_counter += 1
else:
    st.info("No images selected for deletion.")
