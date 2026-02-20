# pages/image_editor.py
import streamlit as st
from pathlib import Path
from PIL import Image, ImageOps
import config

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="Image Crop & Rotate",
    layout="wide"
)

st.title("LifeDrawingGallery — Image Crop & Rotate")

# ---------------- Choose Folder ----------------
IMAGE_FOLDERS = {
    "Raw Images": config.RAW_DIR,
    "Cleaned Images": config.CLEANED_DIR,
    "Processed Images": config.IMAGE_PROCESSING_DIR
}

folder_choice = st.selectbox(
    "Select Image Folder",
    list(IMAGE_FOLDERS.keys())
)

IMAGE_DIR = IMAGE_FOLDERS[folder_choice]
if not IMAGE_DIR.exists():
    st.error(f"Folder not found: {IMAGE_DIR}")
    st.stop()

all_images = sorted(
    [p for p in IMAGE_DIR.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
)

if not all_images:
    st.info("No images found in this folder.")
    st.stop()

# ---------------- Session State ----------------
if "idx" not in st.session_state:
    st.session_state.idx = 0

# ---------------- Thumbnail Scroller ----------------
st.subheader("Preview & Jump to Image")

thumb_cols = st.columns(8)
THUMB_SIZE = 80

for i, img_path in enumerate(all_images[:80]):  # show first 80 thumbnails to avoid heavy load
    with thumb_cols[i % 8]:
        thumb = Image.open(img_path)
        thumb.thumbnail((THUMB_SIZE, THUMB_SIZE))
        if st.button(img_path.name, key=f"thumb_{i}"):
            st.session_state.idx = i

st.write(f"Showing thumbnail navigation for {min(len(all_images), 80)} of {len(all_images)} images.")

# ---------------- Main Navigation ----------------
idx = st.session_state.idx
left, mid, right = st.columns([1, 2, 1])

with left:
    if st.button("⬅ Previous"):
        st.session_state.idx = max(idx - 1, 0)

with right:
    if st.button("Next ➡"):
        st.session_state.idx = min(idx + 1, len(all_images) - 1)

current_path = all_images[st.session_state.idx]
st.write(f"**Editing [{st.session_state.idx+1}/{len(all_images)}]: {current_path.name}**")

# Load image once
image = Image.open(current_path)

# ---------------- Editing Controls ----------------
st.markdown("---")
st.subheader("Crop & Rotate Controls")

# Rotation
rotation = st.radio("Rotate:", ["0°", "90°", "180°", "270°"])
angle_map = {"0°": 0, "90°": 90, "180°": 180, "270°": 270}
angle = angle_map[rotation]

# Cropping
crop_enable = st.checkbox("Enable Crop")
if crop_enable:
    st.write("Select crop box values:")
    width, height = image.size
    
    col1, col2 = st.columns(2)
    with col1:
        x1 = st.number_input("x1", min_value=0, max_value=width, value=0)
        y1 = st.number_input("y1", min_value=0, max_value=height, value=0)
    with col2:
        x2 = st.number_input("x2", min_value=0, max_value=width, value=width)
        y2 = st.number_input("y2", min_value=0, max_value=height, value=height)

# Apply transforms
edited = image.rotate(angle, expand=True)

if crop_enable:
    edited = edited.crop((x1, y1, x2, y2))

# ---------------- Display Edited Image ----------------
st.image(edited, use_column_width=True)

# ---------------- Save / Reset ----------------
col_save, col_reset = st.columns(2)
with col_save:
    if st.button("Save Changes"):
        edited.save(current_path)
        st.success(f"Saved edits to: {current_path.name}")

with col_reset:
    if st.button("Reset"):
        st.session_state.idx = st.session_state.idx  # reload unmodified
        st.experimental_rerun()