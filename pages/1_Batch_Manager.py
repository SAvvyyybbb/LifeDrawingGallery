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

def bulk_unbatch_pending(batch_ids):
    # Only touches images.batch_id / is_stitched and the batches row. images.hash,
    # raw_image_data, processed_image_data, and Supabase storage are untouched, so
    # Discord slash command joins (raw_image_data.hash = images.hash) stay intact.
    # Filters to pending/complete in SQL so a stale UI cannot unbatch stitched work.
    if not batch_ids:
        return 0, 0
    cursor.execute(
        "SELECT id FROM batches WHERE id = ANY(%s) AND status IN ('pending', 'complete')",
        (list(batch_ids),)
    )
    safe_ids = [r['id'] for r in cursor.fetchall()]
    if not safe_ids:
        return 0, 0
    cursor.execute(
        "SELECT COUNT(*) AS c FROM images WHERE batch_id = ANY(%s)",
        (safe_ids,)
    )
    image_count = cursor.fetchone()['c']
    cursor.execute(
        "UPDATE images SET batch_id = NULL, is_stitched = -1 WHERE batch_id = ANY(%s)",
        (safe_ids,)
    )
    cursor.execute("DELETE FROM batches WHERE id = ANY(%s)", (safe_ids,))
    conn.commit()
    return len(safe_ids), image_count

def discard_proposal_images(images_list):
    # Send a list of pool images back to Image Editor triage. For each image:
    #   1. DELETE any orphan images row (batch_id NULL — leftover from a prior unbatch).
    #   2. DELETE the processed_image_data row so it drops out of the Batch Manager pool.
    #   3. Reset raw_image_data.processing=0 so it reappears in the Image Editor.
    # The cleaned_images Supabase file is left orphaned (cheap; periodic cleanup is fine).
    # Raw image, modified_hash, and storage_key_raw are preserved, so re-edit + re-Stage 1
    # produces a fresh processed_image_data row.
    if not images_list:
        return 0
    processed_hashes = [img['hash'] for img in images_list if img.get('hash')]
    file_paths = [img['storage_key_processed'] for img in images_list if img.get('storage_key_processed')]
    raw_hashes = [img['original_hash'] for img in images_list if img.get('original_hash')]
    if not processed_hashes:
        return 0
    if file_paths:
        cursor.execute(
            "DELETE FROM images WHERE file_path = ANY(%s) AND batch_id IS NULL",
            (file_paths,)
        )
    cursor.execute(
        "DELETE FROM processed_image_data WHERE hash = ANY(%s)",
        (processed_hashes,)
    )
    if raw_hashes:
        cursor.execute(
            "UPDATE raw_image_data SET processing = 0 WHERE hash = ANY(%s)",
            (raw_hashes,)
        )
    conn.commit()
    return len(processed_hashes)

# ---------------- Existing Batches (Bulk Unbatch) ----------------
cursor.execute("""
    SELECT b.id, b.batch_name, b.primary_folder, b.secondary_folder, b.expected_count,
           COUNT(i.id) AS image_count
    FROM batches b
    LEFT JOIN images i ON i.batch_id = b.id
    WHERE b.status IN ('pending', 'complete')
    GROUP BY b.id
    ORDER BY b.id DESC
""")
existing_batches = cursor.fetchall()

if existing_batches:
    with st.expander(
        f"📦 Existing Batches ({len(existing_batches)}) — bulk unbatch",
        expanded=True,
    ):
        st.caption(
            "Tick any batches and click Unbatch Selected to send their images back to the "
            "pool below for re-grouping. Raw images, cleaned images, and hashes (used by "
            "Discord slash commands) are preserved — only the batch grouping is removed."
        )

        selected_ids = [b['id'] for b in existing_batches
                        if st.session_state.get(f"bulk_chk_{b['id']}", False)]
        total_imgs_selected = sum(
            b['image_count'] for b in existing_batches if b['id'] in selected_ids
        )

        c_all, c_clr, c_act = st.columns([1, 1, 3])
        with c_all:
            if st.button("Select All", key="bulk_select_all", width='stretch'):
                for b in existing_batches:
                    st.session_state[f"bulk_chk_{b['id']}"] = True
                st.rerun()
        with c_clr:
            if st.button("Clear", key="bulk_clear", width='stretch'):
                for b in existing_batches:
                    st.session_state[f"bulk_chk_{b['id']}"] = False
                st.session_state.bulk_confirming = False
                st.rerun()
        with c_act:
            if not st.session_state.get("bulk_confirming", False):
                if st.button(
                    f"🗑️ Unbatch Selected ({len(selected_ids)})",
                    key="bulk_unbatch_btn",
                    type="primary",
                    width='stretch',
                    disabled=not selected_ids,
                ):
                    st.session_state.bulk_confirming = True
                    st.rerun()
            else:
                st.warning(
                    f"Confirm: unbatch **{len(selected_ids)}** batches and "
                    f"return **{total_imgs_selected}** images to the pool?"
                )
                cc1, cc2 = st.columns(2)
                if cc1.button("Yes, Unbatch", key="bulk_confirm_yes", type="primary", width='stretch'):
                    n_batches, n_imgs = bulk_unbatch_pending(selected_ids)
                    for b in existing_batches:
                        st.session_state[f"bulk_chk_{b['id']}"] = False
                    st.session_state.bulk_confirming = False
                    st.success(f"Unbatched {n_batches} batches. {n_imgs} images returned to the pool.")
                    st.rerun()
                if cc2.button("Cancel", key="bulk_confirm_no", width='stretch'):
                    st.session_state.bulk_confirming = False
                    st.rerun()

        st.divider()

        for b in existing_batches:
            col_chk, col_info = st.columns([1, 30])
            with col_chk:
                st.checkbox(
                    "Mark for bulk unbatch",
                    key=f"bulk_chk_{b['id']}",
                    label_visibility="collapsed",
                    help="Mark for bulk unbatch",
                )
            with col_info:
                expected = b['expected_count'] or 0
                count = b['image_count']
                marker = "✅" if (expected and count == expected) else "⚠️"
                st.write(
                    f"{marker} **{b['batch_name']}** — {count}/{expected} images "
                    f"({b['secondary_folder']} · {b['primary_folder']})"
                )

# ---------------- Data Loading ----------------
with st.spinner("Loading data..."):
    # 1. Unbatched Images (Includes completely new images and ones that failed stitching)
    cursor.execute("""
        SELECT p.*, r.channel_id, r.content_category as discord_channel, r.veto,
               r.poster_id, r.poster_name
        FROM processed_image_data p
        LEFT JOIN raw_image_data r ON p.original_hash = r.hash
        LEFT JOIN images i ON p.storage_key_processed = i.file_path
        WHERE (i.id IS NULL OR i.is_stitched = -1) AND p.avg_r IS NOT NULL
    """)
    unbatched_images = cursor.fetchall()
    
    # 2. Existing Phashes (for duplicate detection)
    # Filter to batch_id IS NOT NULL — unbatched rows (batch_id NULL, often is_stitched=-1)
    # are the SAME images that appear in unbatched_images, so including them would flag
    # every previously-unbatched image as a duplicate of itself.
    cursor.execute("SELECT perceptual_hash FROM images WHERE batch_id IS NOT NULL")
    existing_phashes = set(r['perceptual_hash'] for r in cursor.fetchall())

if not unbatched_images:
    st.info("No new cleaned images found. Please run **Stage 01 (Pre-Processing)** by executing `python3 process_stage1.py` in your terminal first.")
    st.stop()

st.write(f"**Found {len(unbatched_images)} images ready for batching.**")

# ---------------- Batching Logic ----------------
# Build user options from the unbatched pool, ordered by submission count.
user_counts = {}
for img in unbatched_images:
    name = img.get('poster_name') or img.get('poster_id') or 'unknown'
    user_counts[name] = user_counts.get(name, 0) + 1
sorted_users = sorted(user_counts.items(), key=lambda x: (-x[1], x[0]))
user_label_map = {f"{name}  ({count})": name for name, count in sorted_users}

selected_user_labels = st.multiselect(
    "Isolate batches for these users (optional)",
    options=list(user_label_map.keys()),
    key="isolate_users",
    help="Selected users get their own per-user batches (one set of batches per user per aspect/channel). Everyone else falls into default aspect+channel grouping. Leave empty for pure default."
)
isolated_users = {user_label_map[lbl] for lbl in selected_user_labels}

if st.button("Auto-Group into Batches", key="btn_auto_group", type="primary", width='stretch'):
    # Hierarchical Grouping: Aspect -> Channel -> (User only if isolated)
    groups = {}
    for img in unbatched_images:
        aspect = img['category']
        channel = img['discord_channel'] or "Unknown"
        poster_name = img.get('poster_name') or img.get('poster_id') or 'unknown'
        isolated_poster = poster_name if poster_name in isolated_users else None
        key = (aspect, channel, isolated_poster)
        groups.setdefault(key, []).append(img)

    batch_proposals = []
    timestamp = datetime.now().strftime('%m%d_%H%M')
    for (aspect, channel, isolated_poster), imgs in groups.items():
        # ADVANCED SORT: Sort by Color (Hue/Saturation/B&W)
        imgs.sort(key=lambda x: get_color_sort_key(x['avg_r'], x['avg_g'], x['avg_b']))

        tile_w, tile_h, capacity = compute_tile_size(aspect)
        for i in range(0, len(imgs), capacity):
            batch_imgs = imgs[i:i+capacity]
            user_part = f"_{isolated_poster.replace(' ', '_')}" if isolated_poster else ""
            batch_proposals.append({
                "name": f"{aspect}_{channel}{user_part}_{timestamp}_{len(batch_proposals)+1}",
                "aspect": aspect,
                "channel": channel,
                "img_w": tile_w,
                "img_h": tile_h,
                "expected_count": capacity,
                "images": batch_imgs
            })
    st.session_state.batch_proposals = batch_proposals
    if isolated_users:
        st.success(f"Proposed {len(batch_proposals)} batches with {len(isolated_users)} user(s) isolated.")
    else:
        st.success(f"Proposed {len(batch_proposals)} batches.")

# ---------------- Display Proposals ----------------
if "batch_proposals" in st.session_state:

    if "all_batches_expanded" not in st.session_state:
        st.session_state.all_batches_expanded = None # None means use default logic

    col_expand_all, col_collapse_all, col_discard_all = st.columns(3)

    with col_expand_all:
        if st.button("Expand All Batches", key="btn_expand_all_batches", width='stretch'):
            st.session_state.all_batches_expanded = True
            st.rerun()

    with col_collapse_all:
        if st.button("Collapse All Batches", key="btn_collapse_all_batches", width='stretch'):
            st.session_state.all_batches_expanded = False
            st.rerun()

    with col_discard_all:
        if not st.session_state.get("discard_all_confirming", False):
            if st.button(
                f"🗑️ Discard All Proposals ({len(st.session_state.batch_proposals)})",
                key="btn_discard_all",
                type="secondary",
                width='stretch',
                help="Drop every proposal. Images go back to the Image Editor for re-triage (re-run Stage 1 after editing to re-enter the batching pool)."
            ):
                st.session_state.discard_all_confirming = True
                st.rerun()
        else:
            all_images = [img for batch in st.session_state.batch_proposals for img in batch['images']]
            st.warning(
                f"Discard all {len(st.session_state.batch_proposals)} proposals "
                f"and send {len(all_images)} images back to the Image Editor?"
            )
            cc1, cc2 = st.columns(2)
            if cc1.button("Yes", key="discard_all_yes", type="primary", width='stretch'):
                n_returned = discard_proposal_images(all_images)
                del st.session_state.batch_proposals
                st.session_state.discard_all_confirming = False
                st.success(f"Discarded {n_returned} images. Open the Image Editor to re-triage, then re-run Stage 1.")
                st.rerun()
            if cc2.button("Cancel", key="discard_all_no", width='stretch'):
                st.session_state.discard_all_confirming = False
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

        col_sel, col_trash, col_exp = st.columns([1, 1, 19])
        with col_sel:
            # We use a distinct key to avoid ID collisions, and update the dict on change.
            batch['selected'] = st.checkbox("Save", value=batch['selected'], key=f"sel_{i}_{batch['name']}")
        with col_trash:
            if st.button("🗑️", key=f"trash_{i}_{batch['name']}", help="Discard this proposal — images return to the Image Editor for re-triage (re-run Stage 1 after editing to re-enter the batching pool)"):
                discard_proposal_images(batch['images'])
                st.session_state.batch_proposals.pop(i)
                st.rerun()

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
                            img['phash'], img['original_hash']))
                    saved_count += 1
                
                conn.commit()
                st.success(f"Successfully saved {saved_count} selected batches!")
                del st.session_state.batch_proposals
                st.rerun()
            except Exception as e:
                conn.rollback()
                st.error(f"Error saving batches: {e}")

conn.close()
