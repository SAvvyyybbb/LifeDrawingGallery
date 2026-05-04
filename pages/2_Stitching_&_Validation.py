import streamlit as st
import os
import math
from datetime import datetime, timezone
from PIL import Image, ImageOps, ImageDraw, ImageFont
import pandas as pd
import config
from pathlib import Path
import io
import hashlib
import imagehash

st.set_page_config(page_title="Stitching & Validation", layout="wide")

st.title("🧵 Stitching & Validation")
st.markdown("Stitch completed batches into UV maps and validate them before deployment.")

# ---------------- Database Connection ----------------
try:
    conn = config.get_db_connection()
    cursor = conn.cursor(cursor_factory=config.psycopg2.extras.RealDictCursor)
except Exception as e:
    st.error(f"Failed to connect to cloud database: {e}")
    st.stop()

# ---------------- Caching ----------------
@st.cache_data(show_spinner=False, max_entries=500)
def get_cleaned_thumbnail(storage_key, category, size=(150, 150)):
    """Downloads and returns a thumbnail of the image from cleaned_images, cached by storage_key."""
    local_path = config.CLEANED_DIR / category / storage_key
    if not local_path.exists():
        local_path.parent.mkdir(parents=True, exist_ok=True)
        config.download_from_supabase(storage_key, local_path.parent, "cleaned_images")
    
    if local_path.exists():
        try:
            img = Image.open(local_path)
            img.thumbnail(size)
            return img
        except:
            return None
    return None

# ---------------- Load Master List ----------------
master_df = pd.read_csv("MASTER_LIST.csv")
MASTER_NAMES = master_df["Name"].str.replace(".png", "", regex=False).tolist()

# ---------------- Helpers ----------------
def get_local_image_path(storage_key, category):
    local_path = config.CLEANED_DIR / category / storage_key
    if not local_path.exists():
        local_path.parent.mkdir(parents=True, exist_ok=True)
        config.download_from_supabase(storage_key, local_path.parent, "cleaned_images")
    return local_path

def render_batch_grid(batch, images, scale=0.5):
    preview_size = int(config.OUTPUT_SIZE * scale)
    canvas = Image.new("RGB", (preview_size, preview_size), (0, 0, 0))
    
    if not images:
        return canvas
        
    x, y = 0, 0
    max_row_h = 0
    
    for idx, img_row in enumerate(images):
        try:
            local_path = get_local_image_path(img_row["file_path"], img_row["aspect_category"])
            img = Image.open(local_path).convert("RGB")
            
            # The images are already the correct native sizes (e.g. 717x512)
            w, h = img.size
            
            # Scale down for preview
            preview_w = int(w * scale)
            preview_h = int(h * scale)
            
            if x + preview_w > preview_size:
                x = 0
                y += max_row_h
                max_row_h = 0
                
            if y + preview_h > preview_size:
                break
                
            img_resized = img.resize((preview_w, preview_h), Image.LANCZOS)
            canvas.paste(img_resized, (x, y))
            
            x += preview_w
            max_row_h = max(max_row_h, preview_h)
            
        except Exception as e:
            pass
            
    return canvas

def render_batch(batch, images):
    canvas = Image.new("RGB", (config.OUTPUT_SIZE, config.OUTPUT_SIZE), (0,0,0))
    
    if not images:
        return canvas
        
    x, y = 0, 0
    max_row_h = 0
    
    for idx, img_row in enumerate(images):
        try:
            local_path = get_local_image_path(img_row["file_path"], img_row["aspect_category"])
            img = Image.open(local_path).convert("RGB")
            
            # Native database sizes
            w, h = img.size
            
            if x + w > config.OUTPUT_SIZE:
                x = 0
                y += max_row_h
                max_row_h = 0
                
            if y + h > config.OUTPUT_SIZE:
                st.warning(f"Image '{img_row['file_path']}' overflows the 2048 canvas vertically. Skipping this image.")
                break
                
            canvas.paste(img, (x, y))
            
            x += w
            max_row_h = max(max_row_h, h)
        except Exception as e:
            st.error(f"Error rendering image {img_row['file_path']}: {e}")
            
    return canvas

# ---------------- Actions ----------------
def unbatch(batch_id):
    # Set the images back to unbatched and unstitched state
    cursor.execute("UPDATE images SET batch_id = NULL, is_stitched = 0 WHERE batch_id = %s", (batch_id,))
    cursor.execute("DELETE FROM batches WHERE id = %s", (batch_id,))
    conn.commit()
    st.success("Batch unbatched! Images are now back in the unbatched pool.")
    st.rerun()

def save_order(img_updates):
    for img_id, new_order in img_updates:
        cursor.execute("UPDATE images SET manual_order = %s WHERE id = %s", (new_order, img_id))
    conn.commit()
    st.success("Order saved!")
    st.rerun()

# ---------------- Data Loading ----------------
with st.spinner("Loading batches..."):
    cursor.execute("SELECT * FROM batches WHERE status IN ('pending', 'complete', 'stitched', 'validated') ORDER BY id DESC")
    batches = cursor.fetchall()

if not batches:
    st.info("No batches ready for stitching. Go to the Batch Manager first!")
    st.stop()

# ---------------- UI Sections ----------------
tab1, tab2 = st.tabs(["🧵 Pending Stitching", "✅ Pending Validation"])

with st.sidebar:
    st.title("📦 Bulk Actions")
    if st.button("Unbatch ALL Batches", type="secondary", width='stretch', help="Caution: This will delete ALL pending batches and return images to the pool."):
        cursor.execute("UPDATE images SET batch_id = NULL, is_stitched = 0 WHERE batch_id IN (SELECT id FROM batches WHERE status != 'validated')")
        cursor.execute("DELETE FROM batches WHERE status != 'validated'")
        conn.commit()
        st.success("All pending batches cleared!")
        st.rerun()

with tab1:
    pending_stitch = [b for b in batches if b['status'] in ('pending', 'complete')]
    if not pending_stitch:
        st.success("No batches pending stitching!")
    else:
        # Multi-select for unbatching
        st.write(f"Found {len(pending_stitch)} batches ready to be stitched.")
        
        selected_unbatch = st.multiselect("Select batches to unbatch in bulk:", 
                                         options=[b['id'] for b in pending_stitch],
                                         format_func=lambda x: next(b['batch_name'] for b in pending_stitch if b['id'] == x))
        
        if selected_unbatch:
            if st.button(f"Unbatch {len(selected_unbatch)} Selected", type="secondary"):
                for bid in selected_unbatch:
                    cursor.execute("UPDATE images SET batch_id = NULL, is_stitched = 0 WHERE batch_id = %s", (bid,))
                    cursor.execute("DELETE FROM batches WHERE id = %s", (bid,))
                conn.commit()
                st.success("Selected batches unbatched!")
                st.rerun()

        for batch in pending_stitch:
            cursor.execute("SELECT * FROM images WHERE batch_id=%s ORDER BY manual_order", (batch['id'],))
            batch_images = cursor.fetchall()
            
            # Skip orphaned/empty batches
            if not batch_images:
                continue

            with st.expander(f"Stitch: {batch['batch_name']}", expanded=False):
                # 1. Image Ordering & Audit
                st.write("### 1. Arrange & Audit")
                
                img_updates = []
                cols_edit = st.columns(4)
                for j, img_row in enumerate(batch_images):
                    with cols_edit[j % 4]:
                        thumb = get_cleaned_thumbnail(img_row['file_path'], img_row['aspect_category'], size=(80, 80))
                        if thumb:
                            st.image(thumb, width=80)
                        
                        # Check for Veto
                        cursor.execute("SELECT veto FROM raw_image_data WHERE hash = %s", (img_row['hash'],))
                        v_res = cursor.fetchone()
                        if v_res and v_res['veto'] == 1:
                            st.error("🚨 VETOED")
                        
                        new_order = st.number_input("Order", value=int(img_row['manual_order'] or 0), key=f"ord_{img_row['id']}", min_value=0)
                        img_updates.append((img_row['id'], new_order))

                if st.button("Update Order", key=f"upd_{batch['id']}"):
                    save_order(img_updates)

                st.divider()
                
                # 2. Grid Preview
                st.write("### 2. Grid Preview")
                col_prev, col_actions = st.columns([2, 1])
                
                with col_prev:
                    grid_preview = render_batch_grid(batch, batch_images, scale=0.4)
                    st.image(grid_preview, caption="Final Stitch Arrangement Preview", width="stretch")
                
                with col_actions:
                    st.write("### 3. Commit")
                    
                    # Constraint Check: Incomplete batches cannot be stitched
                    expected = batch['expected_count'] or 0
                    current_count = len(batch_images)
                    is_incomplete = current_count < expected
                    
                    if is_incomplete:
                        st.error(f"❌ **Batch Incomplete:** {current_count}/{expected} images. Please add more images to this batch in the Batch Manager before stitching.")
                        st.info("💡 **Tip:** You can use the 'Unbatch' button below to return these images to the pool and regroup them.")
                    
                    target_name = st.selectbox("Assign Master List Name", options=["None"] + MASTER_NAMES, key=f"name_{batch['id']}", disabled=is_incomplete)
                    
                    is_disabled = is_incomplete or (target_name == "None")
                    
                    if st.button("Stitch & Upload", key=f"btn_{batch['id']}", type="primary", disabled=is_disabled):
                        if target_name == "None":
                            st.error("Please assign a name from the Master List first.")
                        else:
                            with st.spinner(f"Stitching {batch['batch_name']} as {target_name}..."):
                                canvas = render_batch(batch, batch_images)
                                
                                # Save and upload
                                uv_name = f"{target_name}.png"
                                temp_path = Path(uv_name)
                                canvas.save(temp_path)
                                
                                storage_key = config.upload_to_supabase(temp_path, "uv_maps")
                                
                                if storage_key:
                                    # Update batch status and name
                                    cursor.execute("UPDATE batches SET status='stitched', batch_name=%s WHERE id=%s", (target_name, batch['id']))
                                    # Record in stitched_phashes
                                    uv_hash = hashlib.sha256(temp_path.read_bytes()).hexdigest()
                                    uv_phash = str(imagehash.phash(canvas))
                                    cursor.execute(
                                        "INSERT INTO stitched_phashes (phash, hash, file_path, batch_id, stitched_date) VALUES (%s,%s,%s,%s,%s)",
                                        (uv_phash, uv_hash, storage_key, batch['id'], datetime.now(timezone.utc).date())
                                    )
                                    st.success(f"Stitched and uploaded as {uv_name}")
                                    conn.commit()
                                    st.rerun()
                                else:
                                    st.error(f"Failed to upload {uv_name}")
                                
                                if temp_path.exists(): temp_path.unlink()

                    if st.button("Unbatch", key=f"unbatch_{batch['id']}", help="Delete this batch and return images to the pool"):
                        unbatch(batch['id'])

with tab2:
    pending_val = [b for b in batches if b['status'] == 'stitched']
    if not pending_val:
        st.info("No batches pending validation.")
    else:
        for batch in pending_val:
            with st.expander(f"Review: {batch['batch_name']}", expanded=False):
                col_v1, col_v2 = st.columns([1, 2])
                
                with col_v1:
                    st.write("**Batch Details**")
                    st.write(f"ID: {batch['id']}")
                    st.write(f"Aspect: {batch['secondary_folder']}")
                    
                    if st.button(f"Mark {batch['batch_name']} as Validated", key=f"val_{batch['id']}", type="primary"):
                        cursor.execute("UPDATE batches SET status='validated' WHERE id=%s", (batch['id'],))
                        conn.commit()
                        st.success("Validated!")
                        st.rerun()
                        
                    if st.button("Unbatch (Rejected)", key=f"unbatch_val_{batch['id']}", help="Something is wrong? Unbatch it."):
                        unbatch(batch['id'])
                    
                    st.divider()
                    st.write("**Original Batch Images:**")
                    cursor.execute("SELECT * FROM images WHERE batch_id=%s ORDER BY manual_order", (batch['id'],))
                    val_batch_images = cursor.fetchall()
                    cols_thumb = st.columns(4)
                    for k, img_row in enumerate(val_batch_images):
                        with cols_thumb[k % 4]:
                            v_thumb = get_cleaned_thumbnail(img_row['file_path'], img_row['aspect_category'], size=(80, 80))
                            if v_thumb:
                                st.image(v_thumb, width=80)

                # Load the UV map from storage
                cursor.execute("SELECT file_path FROM stitched_phashes WHERE batch_id=%s ORDER BY id DESC LIMIT 1", (batch['id'],))
                res = cursor.fetchone()
                if res:
                    uv_url = f"{config.SUPABASE_URL}/storage/v1/object/public/uv_maps/{res['file_path']}"
                    with col_v2:
                        st.image(uv_url, caption="Generated UV Map", width="stretch")

conn.close()
