import streamlit as st
import pandas as pd
from PIL import Image
import config
from pathlib import Path
import io
import shutil
import git_helper
from datetime import datetime

st.set_page_config(page_title="UV Gallery Manager", layout="wide")

# ---------------- Database Connection & Migration ----------------
try:
    conn = config.get_db_connection()
    cursor = conn.cursor(cursor_factory=config.psycopg2.extras.RealDictCursor)
    
    # Ensure notes column exists
    cursor.execute("ALTER TABLE batches ADD COLUMN IF NOT EXISTS notes TEXT DEFAULT ''")
    conn.commit()
except Exception as e:
    st.error(f"Failed to connect to or migrate cloud database: {e}")
    st.stop()

# ---------------- Password Protection ----------------
st.sidebar.title("🔒 Security")
ADMIN_PASSWORD = "admin" # Fallback if not in secrets
try:
    if "ADMIN_PASSWORD" in st.secrets:
        ADMIN_PASSWORD = st.secrets["ADMIN_PASSWORD"]
except: pass

user_pass = st.sidebar.text_input("Enter Admin Password to allow modifications", type="password")
can_modify = (user_pass == ADMIN_PASSWORD)

if user_pass == "":
    st.sidebar.info("🔒 Enter password to unlock deployment actions.")
elif can_modify:
    st.sidebar.success("✅ Password Accepted! You may now modify Live UVs.")
else:
    st.sidebar.error("❌ Incorrect Password.")

# ---------------- Load Master List ----------------
try:
    master_df = pd.read_csv("MASTER_LIST.csv")
    MASTER_FILES = [Path(f).stem for f in master_df["Name"].tolist()]
except Exception as e:
    st.error(f"Error loading MASTER_LIST.csv: {e}")
    st.stop()

st.title("🛡️ UV Gallery Manager")
st.markdown("Manage Live UVs, Pending deployments, and Archives. Ensures 1:1 parity with your MASTER_LIST.")

# ---------------- Fetch DB Records ----------------
cursor.execute("""
    SELECT b.id, b.batch_name, b.status, b.notes, b.timestamp, s.file_path as storage_key, s.hash
    FROM batches b
    LEFT JOIN stitched_phashes s ON b.id = s.batch_id
    WHERE b.status IN ('validated', 'deployed', 'archived')
    ORDER BY b.timestamp DESC
""")
all_records = cursor.fetchall()

# Group records by Master Name
grouped_records = {name: {'live': None, 'pending': [], 'archived': []} for name in MASTER_FILES}
for rec in all_records:
    name = rec['batch_name']
    if name not in grouped_records:
        continue # Stray batch name not in master list
        
    if rec['status'] == 'deployed':
        grouped_records[name]['live'] = rec
    elif rec['status'] == 'validated':
        grouped_records[name]['pending'].append(rec)
    elif rec['status'] == 'archived':
        grouped_records[name]['archived'].append(rec)

# ---------------- Helper Functions ----------------
@st.cache_data(show_spinner=False, max_entries=50)
def get_uv_preview(storage_key):
    if not storage_key: return None
    try:
        data = config.supabase_storage_client.storage.from_("uv_maps").download(storage_key)
        img = Image.open(io.BytesIO(data))
        img.thumbnail((300, 300))
        return img
    except:
        return None

def perform_deployment(target_name, new_batch, old_batch):
    """Handles downloading, archiving, db updates, and git push."""
    uv_dir = Path("Gallery UVs")
    uv_dir.mkdir(exist_ok=True)
    archive_dir = uv_dir / "Archive"
    archive_dir.mkdir(exist_ok=True)
    
    filename = f"{target_name}.png"
    local_path = uv_dir / filename
    
    # 1. Archive the old file if it exists locally
    if local_path.exists() and old_batch:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        old_hash = old_batch['hash'][:8] if old_batch['hash'] else "unk"
        archive_path = archive_dir / f"{target_name}_{timestamp}_{old_hash}.png"
        shutil.copy2(local_path, archive_path)
    
    # 2. Download new version from Supabase
    try:
        image_data = config.supabase_storage_client.storage.from_("uv_maps").download(new_batch['storage_key'])
        local_path.write_bytes(image_data)
    except Exception as e:
        st.error(f"Failed to download from Supabase: {e}")
        return False
        
    # 3. Update Database
    cursor.execute("UPDATE batches SET status = 'archived' WHERE batch_name = %s AND status = 'deployed'", (target_name,))
    cursor.execute("UPDATE batches SET status = 'deployed' WHERE id = %s", (new_batch['id'],))
    conn.commit()
    
    # 4. Git Push
    try:
        repo_root = config.ROOT_DIR
        
        # Streamlit Cloud Authentication Setup
        if "GITHUB_TOKEN" in st.secrets:
            token = st.secrets["GITHUB_TOKEN"]
            user = st.secrets.get("GITHUB_USER", "SAvvyyybbb")
            repo = st.secrets.get("GITHUB_REPO", "LifeDrawingGallery")
            git_helper.setup_git(repo_root, token, user, repo)
            
        git_helper.git_add(repo_root)
        committed = git_helper.git_commit(repo_root, f"Automated Update: {target_name} via UI")
        if committed:
            git_helper.git_push(repo_root)
            st.success(f"Successfully deployed {target_name} and pushed to GitHub!")
            st.balloons()
        else:
            st.info(f"{target_name} updated locally/DB, but no changes detected for Git.")
        return True
    except Exception as e:
        st.error(f"Git Push failed: {e}")
        return False

# ---------------- UI Render ----------------
st.divider()

for target_name in MASTER_FILES:
    data = grouped_records[target_name]
    live = data['live']
    pending = data['pending']
    archived = data['archived']
    
    status_emoji = "🟢" if live else ("🟡" if pending else "🔴")
    
    with st.expander(f"{status_emoji} {target_name} (Live: {'Yes' if live else 'No'} | Archives: {len(archived)})", expanded=(live is None)):
        col_live, col_pend, col_arch = st.columns(3)
        
        # LIVE TRAY
        with col_live:
            st.subheader("🌟 Live Tray")
            if live:
                st.caption(f"Batch ID: {live['id']} | Date: {live['timestamp'].strftime('%Y-%m-%d') if hasattr(live['timestamp'], 'strftime') else live['timestamp']}")
                preview_img = get_uv_preview(live['storage_key'])
                if preview_img:
                    st.image(preview_img, use_container_width=True)
                else:
                    st.warning("Preview not available.")
                
                notes = st.text_area("Notes (Live)", value=live.get('notes', ''), key=f"note_l_{live['id']}")
                if st.button("Save Notes", key=f"save_l_{live['id']}"):
                    cursor.execute("UPDATE batches SET notes = %s WHERE id = %s", (notes, live['id']))
                    conn.commit()
                    st.success("Notes saved.")
            else:
                local_path = Path("Gallery UVs") / f"{target_name}.png"
                if local_path.exists():
                    st.warning("⚠️ Unmanaged Legacy File")
                    st.caption("A file exists in your local Gallery UVs folder, but it is not currently tracked by the new database system. It will be automatically tracked when you deploy your first pending batch here.")
                    st.image(str(local_path), use_container_width=True)
                else:
                    st.error("Missing! No live image for this slot.")

        # PENDING TRAY
        with col_pend:
            st.subheader("⏳ Pending Deployments")
            if not pending:
                st.info("No newly validated batches.")
            for p in pending:
                st.markdown(f"**Batch {p['id']}** ({p['timestamp'].strftime('%Y-%m-%d') if hasattr(p['timestamp'], 'strftime') else p['timestamp']})")
                p_prev = get_uv_preview(p['storage_key'])
                if p_prev:
                    st.image(p_prev, use_container_width=True)
                else:
                    st.warning("Preview not available.")
                
                # Notes
                p_notes = st.text_area("Notes", value=p.get('notes', ''), key=f"note_p_{p['id']}", height=68)
                if st.button("Save Note", key=f"save_p_{p['id']}"):
                    cursor.execute("UPDATE batches SET notes = %s WHERE id = %s", (p_notes, p['id']))
                    conn.commit()
                
                # Action
                if st.button("🚀 Push to Live", key=f"push_{p['id']}", disabled=not can_modify, type="primary"):
                    with st.spinner("Processing..."):
                        if perform_deployment(target_name, p, live):
                            st.rerun()
                if st.button("⏪ Abort & Return to Validation", key=f"abort_{p['id']}", disabled=not can_modify):
                    cursor.execute("UPDATE batches SET status = 'stitched' WHERE id = %s", (p['id'],))
                    conn.commit()
                    st.warning(f"Batch {p['id']} returned to validation.")
                    st.rerun()

        # ARCHIVE TRAY
        with col_arch:
            st.subheader("📚 Archive Tray")
            if not archived:
                st.info("No archives.")
            
            if archived:
                arch_opts = {a['id']: f"ID: {a['id']} - {(a['timestamp'].strftime('%Y-%m-%d') if hasattr(a['timestamp'], 'strftime') else a['timestamp'])}" for a in archived}
                selected_arch_id = st.selectbox("Select Archive to View/Restore:", options=list(arch_opts.keys()), format_func=lambda x: arch_opts[x], key=f"sel_arch_{target_name}")
                
                selected_arch = next((a for a in archived if a['id'] == selected_arch_id), None)
                if selected_arch:
                    a_prev = get_uv_preview(selected_arch['storage_key'])
                    if a_prev:
                        st.image(a_prev, use_container_width=True)
                    else:
                        st.warning("Preview not available.")
                    
                    # Notes
                    a_notes = st.text_area("Archive Notes", value=selected_arch.get('notes', ''), key=f"note_a_{selected_arch['id']}", height=68)
                    if st.button("Save Archive Note", key=f"save_a_{selected_arch['id']}"):
                        cursor.execute("UPDATE batches SET notes = %s WHERE id = %s", (a_notes, selected_arch['id']))
                        conn.commit()

                    # Action
                    if st.button("♻️ Restore to Live", key=f"rest_{selected_arch['id']}", disabled=not can_modify):
                        with st.spinner("Restoring archive to live..."):
                            if perform_deployment(target_name, selected_arch, live):
                                st.rerun()

conn.close()
