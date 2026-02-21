# pages/stage00_image_editor.py

import streamlit as st
from pathlib import Path
from PIL import Image
from streamlit_cropper import st_cropper
import config
import math
import sqlite3
import hashlib
from datetime import datetime, timezone

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="Image Crop & Rotate",
    layout="wide"
)

st.title("Image Crop & Rotate")

st.markdown("---")
st.info("How to use this page.")

st.write("""

This page reads the current contents that have been downloaded from Discord in its source formatting. 

The user (you) will need to check the images within, and use the rotate and crop tools to format these to be stretched into the right resolution in a later stage. You can also change the crop of an image if you want.
For artworks taken without using the screenshot function (the artist took a photo of their work floating in the world), crop the image down to exclude the backgrounds using the tools provided. 
If the artwork was uploaded with the screenshot (and theres a black border) that's perfect, you can leave it as is to be cleaned automatically.

When editing an image:

You can find a dropdown to select a preset aspect ratio to size around the image, this will ensure the cleaned up image will fit the UV map without too much stretching. You can use the rotate tool to help find the best fit.

Note that the outer edge of the red box defines the crop. So anything under, or inside the red line is included in the frame. The preview below should show you what the output looks like.

""")

# ---------------- Database ----------------
DB_PATH = config.DB_DIR / "image_data.db"

# ---------------- Schema Guard ----------------
def ensure_schema():
    """Ensure raw_image_data exists and has all required columns."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS raw_image_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        hash TEXT NOT NULL,
        veto_ind INTEGER DEFAULT 0
    )
    """)
    conn.commit()

    cur.execute("PRAGMA table_info(raw_image_data)")
    cols = [c[1] for c in cur.fetchall()]

    if "modified_hash" not in cols:
        cur.execute("ALTER TABLE raw_image_data ADD COLUMN modified_hash TEXT")
    if "updated_at" not in cols:
        cur.execute("ALTER TABLE raw_image_data ADD COLUMN updated_at TEXT")
    if "processing" not in cols:
        cur.execute("ALTER TABLE raw_image_data ADD COLUMN processing INTEGER DEFAULT 0")
    if "batched" not in cols:
        cur.execute("ALTER TABLE raw_image_data ADD COLUMN batched INTEGER DEFAULT 0")

    conn.commit()
    conn.close()

ensure_schema()

# ---------------- Hash Helper ----------------
def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

# ---------------- DB Update Logic ----------------
def update_modified_hash_by_hash(original_hash, modified_hash):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE raw_image_data
        SET modified_hash = ?,
            processing = 0,
            updated_at = ?
        WHERE hash = ?
    """, (
        modified_hash,
        datetime.now(timezone.utc).isoformat(),
        original_hash
    ))

    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected

# ---------------- Raw Folder ----------------
IMAGE_DIR = config.RAW_DIR

# ✅ MINIMAL FIX: create folder if missing instead of crashing
if not IMAGE_DIR.exists():
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    st.warning(f"Raw folder missing — created: {IMAGE_DIR}")

all_images = sorted(
    [p for p in IMAGE_DIR.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
)
if not all_images:
    st.info("No images found in Raw folder.")
    st.stop()

# ---------------- Session State ----------------
if "selected" not in st.session_state:
    st.session_state.selected = 0
    st.session_state.thumb_page = 0

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

# ---------------- Thumbnail Grid ----------------
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
    step=1
)
rotated = image.rotate(angle, expand=True)

# ---------------- Aspect Ratio Crop ----------------
ratio_choice = st.selectbox(
    "Constrain Crop Aspect Ratio",
    ["None","Square","Portrait","Landscape","Extra Tall","Extra Wide"]
)
aspect_map = {
    "None": None,
    "Square": (1,1),
    "Portrait": (3,5),
    "Landscape": (3,2),
    "Extra Tall": (1,2),
    "Extra Wide": (2,1)
}
cropped_img = st_cropper(
    rotated,
    realtime_update=True,
    aspect_ratio=aspect_map[ratio_choice],
    box_color="#FF0000"
)
st.image(cropped_img, caption="Preview of Crop", width="stretch")

# ---------------- Aspect Classifier ----------------
def classify_aspect(img):
    w,h = img.size
    ratio = w/h
    if ratio < 0.6:
        return "Extra Tall"
    elif ratio < 0.9:
        return "Portrait"
    elif ratio <= 1.1:
        return "Square"
    elif ratio <= 1.8:
        return "Landscape"
    else:
        return "Extra Wide"

# ---------------- Save Logic ----------------
def save_edit(move_next=False):
    try:
        original_hash = sha256_file(current_image_path)

        cropped_img.save(current_image_path)
        new_hash = sha256_file(current_image_path)

        updated = update_modified_hash_by_hash(original_hash, new_hash)
        category = classify_aspect(cropped_img)

        if updated == 0:
            st.warning("No database record matched this image.")
        else:
            st.success(f"Saved — Category: {category}")

        if move_next:
            if st.session_state.selected < len(all_images)-1:
                st.session_state.selected += 1
            if st.session_state.selected >= end_idx and st.session_state.thumb_page < total_pages-1:
                st.session_state.thumb_page += 1
            st.rerun()

    except Exception as e:
        st.error(f"Save failed: {e}")

# ---------------- Buttons ----------------
col_save, col_next, col_reset = st.columns(3)
with col_save:
    if st.button("Save Edited Image"):
        save_edit(False)
with col_next:
    if st.button("Save & Next"):
        save_edit(True)
with col_reset:
    if st.button("Reset Edits"):
        st.rerun()