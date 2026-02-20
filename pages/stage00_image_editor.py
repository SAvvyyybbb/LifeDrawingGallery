# pages/stage00_image_editor.py
import streamlit as st
from pathlib import Path
from PIL import Image
from streamlit_cropper import st_cropper
import config
import math
import sqlite3
import hashlib
import imagehash
from datetime import datetime, timezone

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="Image Crop & Rotate",
    layout="wide"
)

st.title("LifeDrawingGallery — Image Crop & Rotate")

# ---------------- Database ----------------
DB_PATH = config.DB_DIR / "image_data.db"

def update_modified_hash(original_filename, modified_hash):
    """Update raw_image_data with new modified_hash for an edited image"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE raw_image_data SET modified_hash=?, processing=0 WHERE original_filename=?",
        (modified_hash, original_filename)
    )
    conn.commit()
    conn.close()

# ---------------- Choose Folder ----------------
IMAGE_FOLDERS = {
    "Raw Images": config.RAW_DIR,
    "Cleaned Images": config.CLEANED_DIR,
    "Processed Images": config.IMAGE_PROCESSING_DIR
}

folder_choice = st.selectbox("Select Image Folder", list(IMAGE_FOLDERS.keys()))
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

# Reset selection if folder changes
if "last_folder" not in st.session_state or st.session_state.last_folder != folder_choice:
    st.session_state.selected = 0
    st.session_state.thumb_page = 0
    st.session_state.last_folder = folder_choice

# ---------------- Thumbnail Pagination ----------------
THUMBS_PER_PAGE = 24
NUM_COLS = 8
total_pages = math.ceil(len(all_images) / THUMBS_PER_PAGE)

col1, col2, col3 = st.columns([1,2,1])
with col1:
    if st.button("Previous Page") and st.session_state.thumb_page > 0:
        st.session_state.thumb_page -= 1
with col3:
    if st.button("Next Page") and st.session_state.thumb_page < total_pages-1:
        st.session_state.thumb_page += 1

st.write(f"Thumbnail Page {st.session_state.thumb_page+1} / {total_pages}")

start_idx = st.session_state.thumb_page * THUMBS_PER_PAGE
end_idx = min(start_idx + THUMBS_PER_PAGE, len(all_images))
thumb_images = all_images[start_idx:end_idx]

# Display thumbnails
cols = st.columns(NUM_COLS)
for i, img_path in enumerate(thumb_images):
    with cols[i % NUM_COLS]:
        thumb = Image.open(img_path)
        thumb.thumbnail((80, 80))
        if st.button("", key=f"thumb_{start_idx+i}", help=img_path.name):
            st.session_state.selected = start_idx + i
        st.image(thumb, width=80)

current_image_path = all_images[st.session_state.selected]
st.write(f"**Editing [{st.session_state.selected+1}/{len(all_images)}]: {current_image_path.name}**")

image = Image.open(current_image_path)

# ---------------- Rotate ----------------
st.markdown("---")
st.subheader("Rotate & Crop")

angle = st.slider(
    "Rotate Image (degrees)",
    min_value=-180,
    max_value=180,
    value=0,
    step=1,
    help="Negative rotates left, positive rotates right"
)
rotated = image.rotate(angle, expand=True)

# ---------------- Crop with Aspect Ratio ----------------
ratio_choice = st.selectbox(
    "Constrain Crop Aspect Ratio",
    ["None","Square","Portrait","Landscape","Extra Tall","Extra Wide"]
)

# Aspect ratio tuples (width, height)
aspect_map = {
    "None": None,
    "Square": (1,1),
    "Portrait": (3,5),
    "Landscape": (3,2),
    "Extra Tall": (1,2),
    "Extra Wide": (2,1)
}
crop_ratio = aspect_map[ratio_choice]

cropped_img = st_cropper(
    rotated,
    realtime_update=True,
    aspect_ratio=crop_ratio,
    box_color="#FF0000"
)

st.image(cropped_img, caption="Preview of Crop", use_column_width=True)

# ---------------- Save / Next / Reset ----------------
col_save, col_next, col_reset = st.columns(3)

def classify_aspect(img):
    w,h = img.size
    ratio = w/h
    if ratio < 0.6:
        category = "Extra Tall"
    elif 0.6 <= ratio < 0.9:
        category = "Portrait"
    elif 0.9 <= ratio <= 1.1:
        category = "Square"
    elif 1.1 < ratio <= 1.8:
        category = "Landscape"
    else:
        category = "Extra Wide"
    return category

# ---------------- Save Edited Image ----------------
with col_save:
    if st.button("Save Edited Image"):
        try:
            # Save to file
            cropped_img.save(current_image_path)

            # Compute new hashes
            data = current_image_path.read_bytes()
            mod_hash = hashlib.sha256(data).hexdigest()
            mod_phash = str(imagehash.phash(cropped_img))

            # Update raw_image_data
            update_modified_hash(current_image_path.name, mod_hash)

            category = classify_aspect(cropped_img)
            st.success(f"Saved — Aspect Category: {category}")
            st.balloons()
        except Exception as e:
            st.error(f"Error saving image: {e}")

# ---------------- Save & Next ----------------
with col_next:
    if st.button("Save & Next"):
        try:
            cropped_img.save(current_image_path)

            # Update DB with modified hash
            data = current_image_path.read_bytes()
            mod_hash = hashlib.sha256(data).hexdigest()
            update_modified_hash(current_image_path.name, mod_hash)

        except Exception as e:
            st.error(f"Error saving image: {e}")

        if st.session_state.selected < len(all_images)-1:
            st.session_state.selected += 1
        # Update thumbnail page if needed
        if st.session_state.selected >= end_idx and st.session_state.thumb_page < total_pages-1:
            st.session_state.thumb_page += 1
        st.experimental_rerun()

# ---------------- Reset Edits ----------------
with col_reset:
    if st.button("Reset Edits"):
        st.experimental_rerun()