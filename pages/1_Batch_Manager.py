import streamlit as st
import pandas as pd
from PIL import Image
import numpy as np
import config
from datetime import datetime, timezone
import colorsys
import io

st.set_page_config(page_title="Batch Manager", layout="wide")

st.title("📦 Batch Manager")
st.markdown("Group cleaned images into batches for UV map generation. Batches are auto-grouped by Aspect Ratio and Channel, then sorted by color.")

# ---------------- Database Connection ----------------
try:
    conn = config.get_db_connection()
    cursor = conn.cursor(cursor_factory=config.psycopg2.extras.RealDictCursor)
except Exception as e:
    st.error(f"Failed to connect to cloud database: {e}")
    st.stop()

# ---------------- Helpers ----------------
def get_color_sort_key(r, g, b):
    """Returns a sort key that groups B&W (low saturation) together, then sorts by hue."""
    h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)
    # If saturation is very low, it's essentially grayscale
    is_bw = 1 if s < 0.12 else 0
    # Sort order: 
    # 1. Color vs B&W (0 for Color, 1 for B&W)
    # 2. Hue (for Color) or Value (for B&W)
    if is_bw:
        return (1, v) 
    else:
        return (0, h)

def compute_tile_size(category):
    if category == "Square":
        return 512, 512, 16
    elif category == "Landscape":
        return 717, 512, 8
    elif category == "Extra Wide":
        return 1024, 512, 8
    elif category == "Portrait":
        return 512, 717, 8
    elif category == "Extra Tall":
        return 512, 1024, 8
    else:
        return 2048, 2048, 1

# ---------------- Data Loading ----------------
with st.spinner("Loading data..."):
    # 1. Unbatched Images (Includes completely new images and ones that failed stitching)
    cursor.execute("""
        SELECT p.*, r.channel_id, r.content_category as discord_channel, r.veto
        FROM processed_image_data p
        LEFT JOIN raw_image_data r ON p.original_hash = r.hash
        LEFT JOIN images i ON p.storage_key_processed = i.file_path
        WHERE (i.id IS NULL OR i.is_stitched = -1) AND p.avg_r IS NOT NULL
    """)
    unbatched_images = cursor.fetchall()
    
    # 2. Existing Phashes (for duplicate detection)
    cursor.execute("SELECT perceptual_hash FROM images")
    existing_phashes = set(r['perceptual_hash'] for r in cursor.fetchall())

if not unbatched_images:
    st.info("No new cleaned images found. Please run **Stage 01 (Pre-Processing)** by executing `python3 process_stage1.py` in your terminal first.")
    st.stop()

st.write(f"**Found {len(unbatched_images)} images ready for batching.**")

# ---------------- Batching Logic ----------------
if st.button("Auto-Group into Batches"):
    # Hierarchical Grouping: Aspect -> Channel
    groups = {}
    for img in unbatched_images:
        key = (img['category'], img['discord_channel'] or "Unknown")
        if key not in groups:
            groups[key] = []
        groups[key].append(img)
    
    batch_proposals = []
    for (aspect, channel), imgs in groups.items():
        # ADVANCED SORT: Sort by Color (Hue/Saturation/B&W)
        imgs.sort(key=lambda x: get_color_sort_key(x['avg_r'], x['avg_g'], x['avg_b']))
        
        tile_w, tile_h, capacity = compute_tile_size(aspect)
        for i in range(0, len(imgs), capacity):
            batch_imgs = imgs[i:i+capacity]
            batch_proposals.append({
                "name": f"{aspect}_{channel}_{datetime.now().strftime('%m%d_%H%M')}_{len(batch_proposals)+1}",
                "aspect": aspect,
                "channel": channel,
                "img_w": tile_w,
                "img_h": tile_h,
                "expected_count": capacity,
                "images": batch_imgs
            })
    st.session_state.batch_proposals = batch_proposals
    st.success(f"Proposed {len(batch_proposals)} batches.")

# ---------------- Display Proposals ----------------
if "batch_proposals" in st.session_state:

    if "all_batches_expanded" not in st.session_state:
        st.session_state.all_batches_expanded = None # None means use default logic

    col_expand_all, col_collapse_all = st.columns(2)

    with col_expand_all:
        if st.button("Expand All Batches", key="btn_expand_all_batches"):
            st.session_state.all_batches_expanded = True
            st.rerun()

    with col_collapse_all:
        if st.button("Collapse All Batches", key="btn_collapse_all_batches"):
            st.session_state.all_batches_expanded = False
            st.rerun()

    st.subheader("Proposed Batches")
    batch_names = [b['name'] for b in st.session_state.batch_proposals]
        
    # Track phashes in current proposal to find duplicates within the proposal
    proposal_phashes = {}
    for b in st.session_state.batch_proposals:
        for img in b['images']:
            ph = img['phash']
            proposal_phashes[ph] = proposal_phashes.get(ph, 0) + 1

    for i, batch in enumerate(st.session_state.batch_proposals):
        if 'selected' not in batch:
            batch['selected'] = True

        count = len(batch['images'])
        expected = batch['expected_count']
        
        # Check for any alerts in this batch
        has_duplicate = any((img['phash'] in existing_phashes or proposal_phashes[img['phash']] > 1) for img in batch['images'])
        has_veto = any(img.get('veto') == 1 for img in batch['images'])
        
        alert_icon = "🚨" if (has_duplicate or has_veto) else ("✅" if count == expected else "⚠️")
        
        # Determine expanded state based on global toggle or default alert status
        default_expanded = (alert_icon != "✅")
        actual_expanded = default_expanded
        if st.session_state.all_batches_expanded is True:
            actual_expanded = True
        elif st.session_state.all_batches_expanded is False:
            actual_expanded = False

        col_sel, col_exp = st.columns([1, 20])
        with col_sel:
            # We use a distinct key to avoid ID collisions, and update the dict on change.
            batch['selected'] = st.checkbox("Save", value=batch['selected'], key=f"sel_{i}_{batch['name']}")
        
        with col_exp:
            with st.expander(f"{alert_icon} Batch: {batch['name']} ({count}/{expected} images)", expanded=actual_expanded):
                if has_duplicate: st.error("🚩 **Duplicate Alert:** One or more images in this batch appear to be already in the database or duplicated in this proposal.")
                if has_veto: st.warning("🚫 **Veto Alert:** This batch contains an image that has been VETOED (marked as non-art).")
                
                st.write(f"**Aspect:** {batch['aspect']} | **Channel:** {batch['channel']} | **Layout:** {batch['img_w']}x{batch['img_h']}")
                
                if not batch['images']:
                    st.info("This batch is empty.")
                    if st.button(f"🗑️ Delete Empty Batch {i}", key=f"del_batch_{i}"):
                        st.session_state.batch_proposals.pop(i)
                        st.rerun()
                
                cols = st.columns(4)
                for j, img in enumerate(batch['images']):
                    with cols[j % 4]:
                        # DUPLICATE CHECK
                        is_dupe = img['phash'] in existing_phashes or proposal_phashes[img['phash']] > 1
                        is_veto = img.get('veto') == 1
                        
                        image_url = f"{config.SUPABASE_URL}/storage/v1/object/public/cleaned_images/{img['storage_key_processed']}"
                        st.image(image_url, width="stretch")
                        
                        if is_dupe: st.error("🚩 DUPLICATE")
                        if is_veto: st.warning("🚫 VETOED")
                        
                        # Link to Editor
                        if st.button("Edit ✂️", key=f"edit_btn_{i}_{j}"):
                            st.session_state.target_edit_hash = img['original_hash']
                            st.switch_page("pages/0_Image_Editor.py")

                        target_batch = st.selectbox(f"Move to:", batch_names, index=i, key=f"move_sel_{i}_{j}", label_visibility="collapsed")
                        col_btn1, col_btn2 = st.columns(2)
                        if col_btn1.button("Move", key=f"move_btn_{i}_{j}"):
                            if target_batch != batch['name']:
                                target_idx = batch_names.index(target_batch)
                                moved_img = st.session_state.batch_proposals[i]['images'].pop(j)
                                st.session_state.batch_proposals[target_idx]['images'].append(moved_img)
                                st.rerun()
                        if col_btn2.button("Remove", key=f"rem_btn_{i}_{j}"):
                            st.session_state.batch_proposals[i]['images'].pop(j)
                            st.rerun()
                        
                        color_hex = '#%02x%02x%02x' % (int(img['avg_r']), int(img['avg_g']), int(img['avg_b']))
                        st.markdown(f"<div style='height: 5px; width: 100%; background-color: {color_hex};'></div>", unsafe_allow_html=True)

    if st.button("Save and Commit Batches"):
        with st.spinner("Saving batches to cloud..."):
            try:
                saved_count = 0
                for batch in st.session_state.batch_proposals:
                    if not batch.get('selected', True): continue
                    if not batch['images']: continue
                    
                    cursor.execute("""
                        INSERT INTO batches (primary_folder, secondary_folder, status, img_w, img_h, expected_count, batch_name, timestamp)
                        VALUES (%s, %s, 'pending', %s, %s, %s, %s, %s) RETURNING id
                    """, (batch['channel'], batch['aspect'], batch['img_w'], batch['img_h'], batch['expected_count'], batch['name'], datetime.now(timezone.utc)))
                    batch_id = cursor.fetchone()['id']
                    for idx, img in enumerate(batch['images']):
                        cursor.execute("""
                            INSERT INTO images
                            (batch_id, file_path, aspect_category, manual_order, img_w, img_h, avg_r, avg_g, avg_b, perceptual_hash, hash)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (file_path) 
                            DO UPDATE SET 
                                batch_id = EXCLUDED.batch_id,
                                manual_order = EXCLUDED.manual_order,
                                is_stitched = 0
                        """, (batch_id, img['storage_key_processed'], img['category'], idx + 1, 
                            img['width'], img['height'], img['avg_r'], img['avg_g'], img['avg_b'], 
                            img['phash'], img['hash']))
                    saved_count += 1
                
                conn.commit()
                st.success(f"Successfully saved {saved_count} selected batches!")
                del st.session_state.batch_proposals
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Error saving batches: {e}")

conn.close()
