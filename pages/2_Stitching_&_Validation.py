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

def render_uv(images, scale=1.0, verbose=False):
    """Render a UV canvas from a list of image rows. scale<1 = preview; verbose=True shows errors in UI."""
    canvas_size = int(config.OUTPUT_SIZE * scale)
    canvas = Image.new("RGB", (canvas_size, canvas_size), (0, 0, 0))
    if not images:
        return canvas
    x, y = 0, 0
    max_row_h = 0
    for img_row in images:
        try:
            local_path = get_local_image_path(img_row["file_path"], img_row["aspect_category"])
            img = Image.open(local_path).convert("RGB")
            w, h = img.size
            tw, th = int(w * scale), int(h * scale)
            if x + tw > canvas_size:
                x = 0
                y += max_row_h
                max_row_h = 0
            if y + th > canvas_size:
                if verbose:
                    st.warning(
                        f"Image `{img_row['file_path']}` (tile {img_row.get('manual_order', '?')}) "
                        f"would overflow the canvas at y={y}+{th} > {canvas_size} — skipped."
                    )
                break
            tile = img.resize((tw, th), Image.LANCZOS) if scale < 1.0 else img
            canvas.paste(tile, (x, y))
            x += tw
            max_row_h = max(max_row_h, th)
        except Exception as e:
            if verbose:
                st.error(f"Failed to render `{img_row['file_path']}` (tile {img_row.get('manual_order', '?')}): {e}")
    return canvas

# ---------------- Actions ----------------
def unbatch(batch_id):
    cursor.execute("UPDATE images SET batch_id = NULL, is_stitched = -1 WHERE batch_id = %s", (batch_id,))
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

def perform_tile_replacement(batch, old_image_id, replacement_storage_key):
    cursor.execute("SELECT manual_order, aspect_category FROM images WHERE id = %s", (old_image_id,))
    old = cursor.fetchone()
    if not old:
        st.error(f"Target tile (images.id={old_image_id}) not found — it may have already been removed from this batch.")
        return False

    cursor.execute("SELECT * FROM processed_image_data WHERE storage_key_processed = %s", (replacement_storage_key,))
    rep = cursor.fetchone()
    if not rep:
        st.error(f"Replacement image not found in processed_image_data for key: `{replacement_storage_key}`")
        return False

    # Remove old tile (returns it to Batch Manager pool)
    cursor.execute("UPDATE images SET batch_id = NULL, is_stitched = -1 WHERE id = %s", (old_image_id,))

    # Insert replacement at same position
    cursor.execute("""
        INSERT INTO images (batch_id, file_path, aspect_category, manual_order, img_w, img_h,
                            avg_r, avg_g, avg_b, perceptual_hash, hash)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (file_path) DO UPDATE SET
            batch_id = EXCLUDED.batch_id,
            manual_order = EXCLUDED.manual_order,
            is_stitched = 0
    """, (batch['id'], replacement_storage_key, rep['category'], old['manual_order'],
          rep['width'], rep['height'], rep['avg_r'], rep['avg_g'], rep['avg_b'],
          rep['phash'], rep['original_hash']))

    # Re-fetch updated image list and re-stitch (reads our own uncommitted changes)
    cursor.execute("SELECT * FROM images WHERE batch_id=%s ORDER BY manual_order", (batch['id'],))
    new_images = cursor.fetchall()

    canvas = render_uv(new_images, verbose=True)
    target_name = batch['batch_name']
    temp_path = Path(f"{target_name}.png")
    canvas.save(temp_path)

    uv_hash = hashlib.sha256(temp_path.read_bytes()).hexdigest()
    uv_phash = str(imagehash.phash(canvas))

    storage_key = config.upload_to_supabase(temp_path, "uv_maps")
    temp_path.unlink(missing_ok=True)

    if storage_key:
        cursor.execute(
            "INSERT INTO stitched_phashes (phash, hash, file_path, batch_id, stitched_date) VALUES (%s,%s,%s,%s,%s)",
            (uv_phash, uv_hash, storage_key, batch['id'], datetime.now(timezone.utc).date())
        )
        cursor.execute("UPDATE batches SET status='stitched' WHERE id=%s", (batch['id'],))
        conn.commit()
        return True
    else:
        st.error(f"Supabase upload failed for `{target_name}.png` — DB changes rolled back. Check bucket permissions and storage quota.")
        conn.rollback()
        return False

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
        cursor.execute("UPDATE images SET batch_id = NULL, is_stitched = -1 WHERE batch_id IN (SELECT id FROM batches WHERE status != 'validated')")
        cursor.execute("DELETE FROM batches WHERE status != 'validated'")
        conn.commit()
        st.success("All pending batches cleared!")
        st.rerun()

with tab1:
    pending_stitch = [b for b in batches if b['status'] in ('pending', 'complete')]
    if not pending_stitch:
        st.success("No batches pending stitching!")
    else:
        st.write(f"Found {len(pending_stitch)} batches ready to be stitched.")
        st.caption("Need to unbatch in bulk? Use the panel at the top of the **Batch Manager**.")

        for batch in pending_stitch:
            cursor.execute("SELECT * FROM images WHERE batch_id=%s ORDER BY manual_order", (batch['id'],))
            batch_images = cursor.fetchall()

            # Skip orphaned/empty batches
            if not batch_images:
                continue

            with st.expander(f"Stitch: {batch['batch_name']} ({len(batch_images)} images)", expanded=False):
                # 1. Image Ordering & Audit
                st.write("### 1. Arrange & Audit")

                # Batch veto lookup — one query for all images in this batch
                img_hashes = [r['hash'] for r in batch_images if r['hash']]
                if img_hashes:
                    cursor.execute("SELECT hash, veto FROM raw_image_data WHERE hash = ANY(%s)", (img_hashes,))
                    veto_map = {r['hash']: r['veto'] for r in cursor.fetchall()}
                else:
                    veto_map = {}

                img_updates = []
                cols_edit = st.columns(4)
                for j, img_row in enumerate(batch_images):
                    with cols_edit[j % 4]:
                        thumb = get_cleaned_thumbnail(img_row['file_path'], img_row['aspect_category'], size=(80, 80))
                        if thumb:
                            st.image(thumb, width=80)

                        if veto_map.get(img_row['hash']) == 1:
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
                    grid_preview = render_uv(batch_images, scale=0.4)
                    st.image(grid_preview, caption="Final Stitch Arrangement Preview", width="stretch")

                with col_actions:
                    st.write("### 3. Commit")

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
                                canvas = render_uv(batch_images, verbose=True)

                                uv_name = f"{target_name}.png"
                                temp_path = Path(uv_name)
                                canvas.save(temp_path)

                                uv_hash = hashlib.sha256(temp_path.read_bytes()).hexdigest()
                                uv_phash = str(imagehash.phash(canvas))
                                storage_key = config.upload_to_supabase(temp_path, "uv_maps")
                                temp_path.unlink(missing_ok=True)

                                if storage_key:
                                    cursor.execute("UPDATE batches SET status='stitched', batch_name=%s WHERE id=%s", (target_name, batch['id']))
                                    cursor.execute(
                                        "INSERT INTO stitched_phashes (phash, hash, file_path, batch_id, stitched_date) VALUES (%s,%s,%s,%s,%s)",
                                        (uv_phash, uv_hash, storage_key, batch['id'], datetime.now(timezone.utc).date())
                                    )
                                    conn.commit()
                                    st.success(f"Stitched and uploaded as `{uv_name}` → storage key: `{storage_key}`")
                                    st.rerun()
                                else:
                                    st.error(f"Supabase upload failed for `{uv_name}`. Check bucket permissions and storage quota.")

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

                # ---- Tile Replacement ----
                st.divider()
                replace_key = f"replacement_target_{batch['id']}"
                selected_tile_id = st.session_state.get(replace_key)

                with st.expander("🔧 Replace a Tile", expanded=selected_tile_id is not None):
                    st.caption("Select a tile below to swap it with an image from the unbatched pool. The UV will be re-stitched automatically.")

                    tile_cols = st.columns(4)
                    for k, img_row in enumerate(val_batch_images):
                        with tile_cols[k % 4]:
                            v_thumb = get_cleaned_thumbnail(img_row['file_path'], img_row['aspect_category'], size=(80, 80))
                            if v_thumb:
                                st.image(v_thumb, width=80)
                            is_selected = selected_tile_id == img_row['id']
                            btn_label = "✅ Selected" if is_selected else f"Select Tile {img_row['manual_order']}"
                            if st.button(btn_label, key=f"sel_tile_{batch['id']}_{img_row['id']}"):
                                if is_selected:
                                    del st.session_state[replace_key]
                                else:
                                    st.session_state[replace_key] = img_row['id']
                                st.rerun()

                    if selected_tile_id is not None:
                        target_row = next((i for i in val_batch_images if i['id'] == selected_tile_id), None)
                        if target_row is None:
                            del st.session_state[replace_key]
                            st.rerun()

                        st.divider()
                        st.write(f"**Replacing:** Tile {target_row['manual_order']} — `{target_row['file_path']}`")
                        st.write(f"**Choose a replacement** (unbatched `{target_row['aspect_category']}` images):")

                        cursor.execute("""
                            SELECT p.storage_key_processed, p.category, p.phash, r.original_filename
                            FROM processed_image_data p
                            LEFT JOIN raw_image_data r ON p.original_hash = r.hash
                            LEFT JOIN images i ON p.storage_key_processed = i.file_path
                            WHERE (i.id IS NULL OR i.is_stitched = -1)
                              AND p.avg_r IS NOT NULL
                              AND p.category = %s
                            LIMIT 48
                        """, (target_row['aspect_category'],))
                        pool = cursor.fetchall()

                        if not pool:
                            st.warning(f"No unbatched {target_row['aspect_category']} images available in the pool.")
                        else:
                            st.caption(f"{len(pool)} available (showing up to 48)")
                            pool_cols = st.columns(4)
                            for m, pool_img in enumerate(pool):
                                with pool_cols[m % 4]:
                                    p_thumb = get_cleaned_thumbnail(pool_img['storage_key_processed'], pool_img['category'], size=(80, 80))
                                    if p_thumb:
                                        st.image(p_thumb, width=80)
                                    fname = (pool_img.get('original_filename') or pool_img['storage_key_processed'])[:22]
                                    st.caption(fname)
                                    if st.button("Replace ↔", key=f"do_replace_{batch['id']}_{m}"):
                                        with st.spinner("Replacing tile and re-stitching…"):
                                            success = perform_tile_replacement(batch, selected_tile_id, pool_img['storage_key_processed'])
                                        if success:
                                            del st.session_state[replace_key]
                                            st.success("Tile replaced and UV re-stitched. Review the new UV above before validating.")
                                            st.rerun()
                                        else:
                                            st.error("Re-stitch failed. No changes were saved.")

                        if st.button("✕ Cancel", key=f"cancel_replace_{batch['id']}"):
                            del st.session_state[replace_key]
                            st.rerun()

conn.close()
