# pages/0_Image_Editor.py

import streamlit as st
from pathlib import Path
from PIL import Image, ImageOps
from streamlit_cropper import st_cropper
import config
import math
import hashlib
import io
from datetime import datetime, timezone

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="0: Image Editor",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ---------------- Database Connection ----------------
try:
    conn = config.get_db_connection()
    cursor = conn.cursor(cursor_factory=config.psycopg2.extras.RealDictCursor)
except Exception as e:
    st.error(f"Failed to connect to cloud database: {e}")
    st.stop()

# ---------------- Caching ----------------
@st.cache_data(show_spinner=False, max_entries=500)
def get_thumbnail(storage_key, size=(120, 120)):
    local_path = config.RAW_DIR / storage_key
    if not local_path.exists():
        config.download_from_supabase(storage_key, config.RAW_DIR, "raw_images")
    if local_path.exists():
        try:
            img = Image.open(local_path)
            img.thumbnail(size)
            return img
        except:
            return None
    return None

@st.cache_data(show_spinner="Loading image...", max_entries=30)
def get_image_bytes(storage_key):
    """Cache raw file bytes — bytes serialise cheaply so cache hits avoid any disk I/O on reruns."""
    local_path = config.RAW_DIR / storage_key
    if not local_path.exists():
        config.download_from_supabase(storage_key, config.RAW_DIR, "raw_images")
    if local_path.exists():
        return local_path.read_bytes()
    return None

# ---------------- Helpers ----------------
def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def update_modified_hash_by_hash(original_hash, modified_hash, new_storage_key):
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE raw_image_data
        SET modified_hash = %s,
            storage_key_raw = %s,
            processing = 0,
            needs_crop = 0,
            updated_at = %s
        WHERE hash = %s
    """, (modified_hash, new_storage_key, datetime.now(timezone.utc), original_hash))
    conn.commit()

# ---------------- Session State ----------------
if "editor_mode" not in st.session_state:
    st.session_state.editor_mode = "grid" # "grid" or "edit"
if "selected_idx" not in st.session_state:
    st.session_state.selected_idx = 0
if "grid_page" not in st.session_state:
    st.session_state.grid_page = 0

# ---------------- Fetch Unprocessed Images ----------------
IMAGE_DIR = config.RAW_DIR
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

target = st.session_state.get("target_edit_hash")

if target:
    cursor.execute("""
        SELECT hash, storage_key_raw, content_category, original_filename, needs_crop, channel_id, created_at
        FROM raw_image_data 
        WHERE (processing = 0 OR hash = %s) AND veto = 0 AND storage_key_raw IS NOT NULL
        ORDER BY CASE WHEN hash = %s THEN 1 ELSE 0 END DESC, needs_crop DESC, created_at DESC
    """, (target, target))
else:
    cursor.execute("""
        SELECT hash, storage_key_raw, content_category, original_filename, needs_crop, channel_id, created_at
        FROM raw_image_data 
        WHERE processing = 0 AND veto = 0 AND storage_key_raw IS NOT NULL
        ORDER BY needs_crop DESC, created_at DESC
    """)
    
db_images = cursor.fetchall()

# Support jump from Batch Manager
if target and db_images:
    st.session_state.pop("target_edit_hash", None)
    for i, row in enumerate(db_images):
        if row['hash'] == target:
            st.session_state.selected_idx = i
            st.session_state.editor_mode = "edit"
            break

if not db_images:
    st.title("🖼️ Image Editor")
    st.info("No unprocessed images found. Everything is clean!")
    st.stop()


# ---------------- Grid View ----------------
if st.session_state.editor_mode == "grid":
    st.title("🖼️ Image Triage")
    st.write(f"Showing {len(db_images)} pending images. Flagged items (⚠️) are surfaced first.")
    
    THUMBS_PER_PAGE = 48
    NUM_COLS = 6
    total_pages = math.ceil(len(db_images) / THUMBS_PER_PAGE)
    
    col_p1, col_p2, col_p3 = st.columns([1, 2, 1])
    with col_p1:
        if st.button("◀ Previous Page", disabled=(st.session_state.grid_page == 0)):
            st.session_state.grid_page -= 1
            st.rerun()
    with col_p3:
        if st.button("Next Page ▶", disabled=(st.session_state.grid_page == total_pages - 1)):
            st.session_state.grid_page += 1
            st.rerun()
    with col_p2:
        st.write(f"Page {st.session_state.grid_page + 1} of {total_pages}")

    start_idx = st.session_state.grid_page * THUMBS_PER_PAGE
    end_idx = min(start_idx + THUMBS_PER_PAGE, len(db_images))
    page_records = db_images[start_idx:end_idx]
    
    cols = st.columns(NUM_COLS)
    for i, row in enumerate(page_records):
        idx = start_idx + i
        with cols[i % NUM_COLS]:
            thumb = get_thumbnail(row['storage_key_raw'])
            if thumb:
                st.image(thumb, width='stretch')

                label = f"[{idx+1}] {row['original_filename'][:15]}..."
                if row['needs_crop']: label = "⚠️ " + label

                col_open, col_veto = st.columns([4, 1])
                with col_open:
                    if st.button(label, key=f"sel_{idx}", width='stretch'):
                        st.session_state.selected_idx = idx
                        st.session_state.editor_mode = "edit"
                        st.rerun()
                with col_veto:
                    if st.button("🚫", key=f"veto_{idx}", width='stretch', help="Veto (mark as not art)"):
                        cursor.execute("UPDATE raw_image_data SET veto = 1 WHERE hash = %s", (row['hash'],))
                        conn.commit()
                        st.rerun()
                st.caption(f"Channel: {row['content_category'] or '?'}")
            else:
                st.error("Error")

# ---------------- Edit Mode ----------------
else:
    st.title("✂️ Manual Crop & Rotate")
    
    if st.button("⬅ Back to Grid"):
        st.session_state.editor_mode = "grid"
        st.rerun()
    
    selected_row = db_images[st.session_state.selected_idx]
    original_hash = selected_row['hash']
    selected_storage_key = selected_row['storage_key_raw']
    
    img_bytes = get_image_bytes(selected_storage_key)
    if not img_bytes:
        st.error("Could not load image from storage.")
        st.stop()

    col_main, col_ctrl = st.columns([3, 1])

    with col_main:
        # exif_transpose bakes any EXIF rotation into the pixel data so the
        # cropper display and the actual pixel coordinates always match
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(img_bytes)))
        
        # Header Info
        st.subheader(f"Editing: {selected_row['original_filename']}")
        if selected_row['needs_crop']:
            st.warning("🚨 **Notice:** Auto-cropping failed. Manual crop required.")
            
        # Controls in col_ctrl
        with col_ctrl:
            st.write("### ℹ️ Info")
            st.write(f"**Index:** {st.session_state.selected_idx + 1}")
            st.write(f"**Channel:** {selected_row['content_category']}")
            st.write(f"**Channel ID:** `{selected_row['channel_id']}`")
            st.write(f"**Date:** {selected_row['created_at'].strftime('%Y-%m-%d')}")
            
            st.divider()
            st.write("### 🛠️ Controls")
            angle = st.slider("🔄 Rotate (degrees)", -180, 180, 0, 1)
            ratio_choice = st.selectbox("📐 Aspect Ratio Guide", ["None","Square","Portrait","Landscape","Extra Tall","Extra Wide"])
            aspect_map = {"None": None, "Square": (1,1), "Portrait": (3,5), "Landscape": (3,2), "Extra Tall": (1,2), "Extra Wide": (2,1)}
            
            st.divider()

        # Pre-scale to 700px — this matches st_cropper's internal max exactly.
        # Passing should_resize_image=False bypasses the library's own resize step,
        # so the returned box coords are directly in the pre-scaled pixel space with
        # no compounding scale factors to worry about.
        MAX_DISPLAY_PX = 700
        orig_w, orig_h = image.size
        display_scale = min(1.0, MAX_DISPLAY_PX / max(orig_w, orig_h))
        display_img = (
            image.resize((int(orig_w * display_scale), int(orig_h * display_scale)), Image.LANCZOS)
            if display_scale < 1.0 else image
        )

        rotated_display = display_img.rotate(angle, expand=True)

        # streamlit_cropper has two traps:
        #   1. realtime_update=False requires the user to DOUBLE-CLICK the canvas
        #      before the box coords reach Python; otherwise saves crop at the
        #      library's default 20%-80% rect.
        #   2. On every rerun, a JS useEffect re-applies the rect_* args back onto
        #      the box, snapping it to whatever default_coords resolves to. We feed
        #      the user's last box back in so the visible box and Python's coords
        #      stay locked together. Keyed on (image, angle, aspect) so the box
        #      resets when any of those change.
        cropper_state_key = (selected_storage_key, angle, ratio_choice)
        if st.session_state.get("cropper_state_key") != cropper_state_key:
            st.session_state.cropper_state_key = cropper_state_key
            st.session_state.pop("cropper_box", None)

        prev_box = st.session_state.get("cropper_box")
        default_coords = (
            (prev_box['left'],
             prev_box['left'] + prev_box['width'],
             prev_box['top'],
             prev_box['top'] + prev_box['height'])
            if prev_box else None
        )

        box = st_cropper(
            rotated_display,
            realtime_update=True,
            should_resize_image=False,
            aspect_ratio=aspect_map[ratio_choice],
            box_color="#FF0000",
            return_type='box',
            default_coords=default_coords,
            key=f"cropper_{selected_storage_key}_{angle}_{ratio_choice}",
        )
        left = box.get('left', 0)
        top = box.get('top', 0)
        width = box.get('width', rotated_display.width)
        height = box.get('height', rotated_display.height)

        st.session_state.cropper_box = {
            'left': left, 'top': top, 'width': width, 'height': height
        }

        # Scale box back to full-resolution coordinates
        if display_scale < 1.0:
            left   = int(left   / display_scale)
            top    = int(top    / display_scale)
            width  = int(width  / display_scale)
            height = int(height / display_scale)

        rotated_full = image.rotate(angle, expand=True)
        cropped_img = rotated_full.crop((left, top, left + width, top + height))

        with col_ctrl:
            def do_save():
                temp_path = IMAGE_DIR / "temp_crop.jpg"
                save_img = cropped_img.convert('RGB') if cropped_img.mode == 'RGBA' else cropped_img
                save_img.save(temp_path, format="JPEG")
                new_hash = sha256_file(temp_path)
                final_path = IMAGE_DIR / f"{new_hash}.jpg"
                temp_path.rename(final_path)
                new_key = config.upload_to_supabase(final_path, "raw_images")
                if new_key:
                    update_modified_hash_by_hash(original_hash, new_hash, new_key)
                    return True
                return False

            # Save Actions
            st.write("### 💾 Actions")
            if st.button("💾 Save Current Image", type="primary", width='stretch', help="Save the cropped and rotated version, and stay on this image."):
                if do_save():
                    st.success("Saved!")
                    st.rerun()

            if st.button("⏩ Save & Load Next", type="primary", width='stretch', help="Save changes and automatically jump to the next image in the queue."):
                if do_save():
                    if st.session_state.selected_idx < len(db_images)-1:
                        st.session_state.selected_idx += 1
                    else:
                        st.session_state.editor_mode = "grid"
                    st.rerun()

            if st.button("🚫 Veto (Not Art)", type="secondary", width='stretch', help="Mark this image as invalid/not art so it won't be processed."):
                cursor.execute("UPDATE raw_image_data SET veto = 1 WHERE hash = %s", (original_hash,))
                conn.commit()
                st.success("Vetoed.")
                if st.session_state.selected_idx < len(db_images)-1:
                    st.session_state.selected_idx += 1
                else:
                    st.session_state.editor_mode = "grid"
                st.rerun()

    # Preload adjacent images into cache so navigation feels instant
    for preload_idx in (st.session_state.selected_idx + 1, st.session_state.selected_idx - 1):
        if 0 <= preload_idx < len(db_images):
            get_image_bytes(db_images[preload_idx]['storage_key_raw'])

conn.close()

