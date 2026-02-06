import streamlit as st
from pathlib import Path
<<<<<<< HEAD
from PIL import Image
import numpy as np
import imagehash
import sqlite3
import hashlib
from datetime import datetime, timezone
import config

# ---------------- Config ----------------
RAW_DIR = config.RAW_DIR
PROCESSED_DIR = config.CLEANED_DIR
DB_PATH = config.DB_DIR / "image_data.db"
TOLERANCE = config.TOLERANCE

# ---------------- Helpers ----------------
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def normalize_extension(ext: str) -> str:
    ext = ext.lower()
    if ext == ".jpeg":
        return ".jpg"
    return ext

def init_db():
    """Initialize DB and tables for Stage 0 processing."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Table for raw image ingestion
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_image_data (
            hash TEXT PRIMARY KEY,
            phash TEXT,
            poster_id INTEGER,
            poster_name TEXT,
            message_id INTEGER,
            channel_id INTEGER,
            original_filename TEXT,
            created_at TEXT,
            processing INTEGER DEFAULT 0,
            batched INTEGER DEFAULT 0
        )
    """)

    # Table for processed images
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_image_data (
            hash TEXT PRIMARY KEY,
            phash TEXT,
            original_hash TEXT,
            category TEXT,
            width INTEGER,
            height INTEGER,
            created_at TEXT
        )
    """)

    conn.commit()
    return conn, cursor

# ---------------- Page UI ----------------
st.title("Stage 0: Preprocess Raw Images (Optional)")

raw_files = [f for f in RAW_DIR.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg")]
total_raw = len(raw_files)
st.write(f"Found {total_raw} image(s) in Raw folder.")

if total_raw == 0:
    st.info("No images found in Raw folder. Stage 0 skipped.")
else:
    if st.button("Run Stage 0: Process Raw Images"):
        conn, cursor = init_db()
        success_count = 0
        failed = []

        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, path in enumerate(raw_files):
            try:
                data = path.read_bytes()
                original_hash = sha256_bytes(data)
                image = Image.open(path)
                if image.mode == 'RGBA':
                    image = image.convert('RGB')
                original_phash = imagehash.phash(image)

                # ---------------- Log raw image ----------------
                cursor.execute("""
                    INSERT OR IGNORE INTO raw_image_data (hash, phash, created_at, processing)
                    VALUES (?, ?, ?, 0)
                """, (original_hash, str(original_phash), datetime.now(timezone.utc).isoformat()))

                # ---------------- Remove black borders ----------------
                arr = np.array(image)
                mask = np.all(arr > TOLERANCE, axis=-1)
                coords = np.argwhere(mask)
                if coords.size == 0:
                    failed.append(path.name)
                    continue
                y0, x0 = coords.min(axis=0)
                y1, x1 = coords.max(axis=0) + 1
                cropped = image.crop((x0, y0, x1, y1)) \
                    if (x1-x0 < image.width*0.95 or y1-y0 < image.height*0.95) else image

                # ---------------- Aspect ratio classification ----------------
                w, h = cropped.size
                ratio = w/h
                if ratio < 0.6: category = "Extra Tall"
                elif 0.6 <= ratio < 0.9: category = "Portrait"
                elif 0.9 <= ratio <= 1.1: category = "Square"
                elif 1.1 < ratio <= 1.8: category = "Landscape"
                else: category = "Extra Wide"

                # ---------------- Resize ----------------
                sizes = {
                    "Square": (512,512),
                    "Portrait": (512,717),
                    "Extra Tall": (512,1024),
                    "Landscape": (717,512),
                    "Extra Wide": (1024,512)
                }
                target_w, target_h = sizes[category]
                resized = cropped.resize((target_w,target_h), Image.Resampling.LANCZOS)

                # ---------------- Save processed image ----------------
                output_dir = PROCESSED_DIR / category
                output_dir.mkdir(parents=True, exist_ok=True)
                out_path = output_dir / path.name
                resized.save(out_path)
                path.unlink()  # remove raw image

                # ---------------- Log processed image ----------------
                processed_hash = sha256_bytes(resized.tobytes())
                processed_phash = imagehash.phash(resized)
                cursor.execute("""
                    INSERT OR REPLACE INTO processed_image_data (
                        hash, phash, original_hash, category, width, height, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    processed_hash, str(processed_phash), original_hash,
                    category, resized.width, resized.height,
                    datetime.now(timezone.utc).isoformat()
                ))

                # ---------------- Update processing flag ----------------
                cursor.execute("""
                    UPDATE raw_image_data
                    SET processing=1
                    WHERE hash=?
                """, (original_hash,))

                conn.commit()
                success_count += 1

            except Exception as e:
                failed.append(path.name)
                print(f"Error processing {path.name}: {e}")

            progress_bar.progress((i+1)/total_raw)
            status_text.text(f"Processed {i+1}/{total_raw} images...")

        st.success("Stage 0 processing complete!")
        st.write(f"Total images: {total_raw}")
        st.write(f"Successfully processed: {success_count}")
        st.write(f"Failed images: {len(failed)}")
        if failed:
            st.warning("Failed images:")
            st.write(failed)
        conn.close()
=======
from PIL import Image, ImageOps
from streamlit_cropper import st_cropper
import math
import config
from io import BytesIO
import base64
import time  # for delay

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="Stage 0 Image Editor",
    layout="wide"
)

st.title("Stage 0: Raw Image Editor")

RAW_DIR: Path = config.RAW_DIR

# ---------------- Load Images ----------------
raw_images = sorted(
    [p for p in RAW_DIR.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
)

if not raw_images:
    st.info(f"No images found in {RAW_DIR}")
    st.stop()

# ---------------- Session State ----------------
if "selected_file" not in st.session_state:
    st.session_state.selected_file = raw_images[0].name

if "rotate_angle" not in st.session_state:
    st.session_state.rotate_angle = 0

if "aspect_label" not in st.session_state:
    st.session_state.aspect_label = "Free"

if "page" not in st.session_state:
    st.session_state.page = 1

if "refresh_trigger" not in st.session_state:
    st.session_state["refresh_trigger"] = 0  # dummy variable to trigger refresh

# ---------------- Aspect Ratio Presets ----------------
ASPECT_RATIOS = {
    "Free": None,
    "Square (512×512)": (1, 1),
    "Portrait (512×717)": (512, 717),
    "Extra Tall (512×1024)": (512, 1024),
    "Landscape (717×512)": (717, 512),
    "Extra Wide (1024×512)": (1024, 512),
}

# ---------------- Pagination Config ----------------
PAGE_SIZE = 32  # 8 columns × 4 rows
TOTAL_PAGES = max(1, math.ceil(len(raw_images) / PAGE_SIZE))
st.session_state.page = min(st.session_state.page, TOTAL_PAGES)
start = (st.session_state.page - 1) * PAGE_SIZE
end = start + PAGE_SIZE
page_images = raw_images[start:end]

# ---------------- Pagination Controls ----------------
st.markdown("### Image Pages")
st.markdown(f"**Total Images:** {len(raw_images)}")

pcol1, pcol2, pcol3 = st.columns([1, 2, 1])
with pcol1:
    if st.button("⬅ Previous", disabled=st.session_state.page <= 1):
        st.session_state.page -= 1
with pcol2:
    st.markdown(
        f"<div style='text-align:center;'>Page {st.session_state.page} of {TOTAL_PAGES}</div>",
        unsafe_allow_html=True
    )
with pcol3:
    if st.button("Next ➡", disabled=st.session_state.page >= TOTAL_PAGES):
        st.session_state.page += 1

# ---------------- Thumbnail Selector ----------------
def thumbnail_selector(images, columns=8, thumb_size=120):
    st.markdown("### Select Image")
    cols = st.columns(columns)

    for idx, img_path in enumerate(images):
        col = cols[idx % columns]

        with col:
            with Image.open(img_path) as im:
                thumb = ImageOps.exif_transpose(im).convert("RGB")
                thumb.thumbnail((thumb_size, thumb_size))

            # Button above thumbnail
            if st.button(" ", key=f"select_{img_path.name}", use_container_width=True):
                st.session_state.selected_file = img_path.name

            st.image(thumb, use_container_width=True)

# ---------------- Image Selection ----------------
thumbnail_selector(page_images)

selected_file = st.session_state.selected_file
image_path = RAW_DIR / selected_file

# ---------------- Load Image ----------------
with Image.open(image_path) as im:
    image = ImageOps.exif_transpose(im).convert("RGB").copy()

# ---------------- Rotation ----------------
rotate_angle = st.slider(
    "Rotate Image (degrees)",
    min_value=-180,
    max_value=180,
    value=st.session_state.rotate_angle
)
st.session_state.rotate_angle = rotate_angle

if rotate_angle != 0:
    image = image.rotate(-rotate_angle, expand=True)

# ---------------- Aspect Ratio Selection ----------------
aspect_label = st.radio(
    "Crop Aspect Ratio",
    options=list(ASPECT_RATIOS.keys()),
    horizontal=True,
    key="aspect_label"
)
aspect_ratio = ASPECT_RATIOS[aspect_label]

# ---------------- Cropping with side-by-side preview ----------------
st.markdown("### Crop Image")
st.write("Drag the crop box. Aspect ratio is enforced if selected.")

col_cropper, col_arrow, col_preview = st.columns([3, 0.3, 3])

with col_cropper:
    cropped_image = st_cropper(
        image,
        realtime_update=True,
        box_color="#FF0000",
        aspect_ratio=aspect_ratio
    )

with col_arrow:
    st.markdown(
        "<div style='font-size:48px; text-align:center; line-height:150px;'>→</div>",
        unsafe_allow_html=True
    )

# ---------------- Function to display images with no rounding ----------------
def display_square_image(image, caption=""):
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    img_str = base64.b64encode(buffer.getvalue()).decode()
    html = f"""
    <div style="display:inline-block;">
        <img src="data:image/png;base64,{img_str}" style="border-radius:0; width:100%;">
        <p style="text-align:center;">{caption}</p>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)

with col_preview:
    display_square_image(cropped_image, "Cropped Preview")

# ---------------- Save Edited Image with 0.5s auto-refresh ----------------
st.markdown("### Save Edited Image")
if st.button("Save Edited Image"):
    cropped_image.save(image_path)
    st.success(f"Saved image and overwrote original file:\n{image_path}")

    # Wait 0.5s
    time.sleep(0.5)

    # Trigger rerun by updating dummy session state variable
    st.session_state["refresh_trigger"] += 1
>>>>>>> 8bf44ef04b181bc2f2ad841cd166aab13476240f
