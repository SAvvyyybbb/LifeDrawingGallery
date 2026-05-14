import streamlit as st
import pandas as pd
from PIL import Image
import config
from pathlib import Path
import io
import hmac
import shutil
import subprocess
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
ADMIN_PASSWORD = config.get_secret("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    st.error("ADMIN_PASSWORD is not set in Streamlit secrets. Deployment actions are disabled.")
    ADMIN_PASSWORD = ""

user_pass = st.sidebar.text_input("Enter Admin Password to allow modifications", type="password")
can_modify = bool(user_pass) and hmac.compare_digest(user_pass, ADMIN_PASSWORD)

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

def get_git_sync_status():
    """Return (uncommitted, unpushed) string summaries for Gallery UVs/."""
    uncommitted, unpushed = "", ""
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain", "Gallery UVs/"],
            cwd=str(config.ROOT_DIR), capture_output=True, text=True
        )
        uncommitted = r.stdout.strip()
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["git", "log", "--oneline", "origin/main..HEAD"],
            cwd=str(config.ROOT_DIR), capture_output=True, text=True
        )
        unpushed = r.stdout.strip()
    except Exception:
        pass
    return uncommitted, unpushed

def perform_push_only():
    """Stage, commit (if needed), and push Gallery UVs/ without touching the DB.
    Used to recover from a previously failed push."""
    try:
        token = config.get_secret("GITHUB_TOKEN")
        if not token:
            st.error("GITHUB_TOKEN is not set in Streamlit secrets.")
            return False
        repo_root = config.ROOT_DIR
        auth_url = git_helper.setup_git(repo_root, token)
        git_helper.git_add(repo_root)
        git_helper.git_commit(repo_root, "Repair: push previously failed UV deployment")
        git_helper.git_push(repo_root, auth_url)
        return True
    except Exception as e:
        st.error(f"Push failed: {e}")
        return False

def perform_repush(target_name, live_batch):
    """Fix a DB/GitHub desync: archive the current GitHub file, re-download the
    DB-deployed version from Supabase, and push both to GitHub.
    Does NOT modify the database — use when the DB is correct but GitHub is not."""
    uv_dir = Path("Gallery UVs")
    uv_dir.mkdir(exist_ok=True)
    archive_dir = uv_dir / "Archive"
    archive_dir.mkdir(exist_ok=True)

    filename = f"{target_name}.png"
    local_path = uv_dir / filename
    temp_path = uv_dir / f".{target_name}_repush.tmp"

    # 1. Download the Supabase-deployed version to temp first
    try:
        image_data = config.supabase_storage_client.storage.from_("uv_maps").download(live_batch['storage_key'])
        temp_path.write_bytes(image_data)
    except Exception as e:
        st.error(f"Failed to download deployed UV from Supabase: {e}")
        return False

    # 2. Archive whatever is currently on disk (= the current GitHub version)
    archived_name = None
    if local_path.exists():
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archived_name = f"{target_name}_{timestamp}_pre-resync.png"
            shutil.copy2(local_path, archive_dir / archived_name)
        except Exception as e:
            st.warning(f"Could not archive current file (non-critical): {e}")

    # 3. Replace with Supabase version
    temp_path.replace(local_path)

    # 4. Push — includes both the updated UV and the newly archived copy
    token = config.get_secret("GITHUB_TOKEN")
    if not token:
        st.error("GITHUB_TOKEN not set. Files written locally but not pushed.")
        return False
    try:
        repo_root = config.ROOT_DIR
        auth_url = git_helper.setup_git(repo_root, token)
        git_helper.git_add(repo_root)
        git_helper.git_commit(repo_root, f"Re-sync: restore deployed UV for {target_name}")
        git_helper.git_push(repo_root, auth_url)
        if archived_name:
            st.info(f"Previous GitHub file archived as `Gallery UVs/Archive/{archived_name}`")
        return True
    except Exception as e:
        st.error(f"Git push failed: {e}")
        return False

def perform_deployment(target_name, new_batch, old_batch):
    """Download → archive → replace local file → git push → DB update.

    Git push happens BEFORE the DB is updated so that a push failure leaves
    everything unchanged and clicking Push to Live again is safe (idempotent).
    """
    uv_dir = Path("Gallery UVs")
    uv_dir.mkdir(exist_ok=True)
    archive_dir = uv_dir / "Archive"
    archive_dir.mkdir(exist_ok=True)

    filename = f"{target_name}.png"
    local_path = uv_dir / filename
    temp_path = uv_dir / f".{target_name}_deploying.tmp"

    # 1. Download new UV to a temp file — abort before touching anything if this fails
    try:
        image_data = config.supabase_storage_client.storage.from_("uv_maps").download(new_batch['storage_key'])
        temp_path.write_bytes(image_data)
    except Exception as e:
        st.error(f"Failed to download from Supabase: {e}")
        return False

    # 2. Archive the current live file (best-effort, non-fatal)
    if local_path.exists() and old_batch:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            old_hash = old_batch['hash'][:8] if old_batch['hash'] else "unk"
            archive_path = archive_dir / f"{target_name}_{timestamp}_{old_hash}.png"
            shutil.copy2(local_path, archive_path)
        except Exception as e:
            st.warning(f"Could not archive old file (non-critical): {e}")

    # 3. Atomically replace local file
    temp_path.replace(local_path)

    # 4. Git push — BEFORE updating the DB so a failure leaves DB unchanged
    token = config.get_secret("GITHUB_TOKEN")
    if not token:
        st.error(
            "GITHUB_TOKEN is not set. Local file has been saved but the database and GitHub "
            "have **not** been updated. Add the secret and click Push to Live again to retry."
        )
        return False

    try:
        repo_root = config.ROOT_DIR
        auth_url = git_helper.setup_git(repo_root, token)
        git_helper.git_add(repo_root)
        git_helper.git_commit(repo_root, f"Deploy: {target_name}")
        git_helper.git_push(repo_root, auth_url)
    except Exception as e:
        st.error(
            f"**Git push failed.** The local file is saved correctly but the database has not been "
            f"updated. Click **Push to Live** again to retry — it is safe to do so.\n\n`{e}`"
        )
        return False

    # 5. DB update — only reached after a confirmed successful push
    cursor.execute(
        "UPDATE batches SET status = 'archived' WHERE batch_name = %s AND status = 'deployed'",
        (target_name,)
    )
    cursor.execute("UPDATE batches SET status = 'deployed' WHERE id = %s", (new_batch['id'],))
    conn.commit()

    st.success(f"✅ {target_name} deployed and pushed to GitHub!")
    st.balloons()
    return True

# ---------------- UI Render ----------------

# Sync status banner — catches any previous push failure immediately on page load
uncommitted, unpushed = get_git_sync_status()
if uncommitted or unpushed:
    with st.container(border=True):
        st.warning("⚠️ **GitHub out of sync** — local Gallery UVs differ from what's on GitHub.")
        c1, c2 = st.columns(2)
        with c1:
            if uncommitted:
                st.write("**Uncommitted local changes:**")
                st.code(uncommitted)
        with c2:
            if unpushed:
                st.write("**Committed but not yet pushed:**")
                st.code(unpushed)
        if can_modify:
            if st.button("🔄 Repair: Push to GitHub Now", type="primary", width='stretch'):
                with st.spinner("Pushing to GitHub..."):
                    if perform_push_only():
                        st.success("✅ Push successful! GitHub is now up to date.")
                        st.rerun()
        else:
            st.info("🔒 Enter the admin password in the sidebar to enable the repair push.")

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
                    st.image(preview_img, width='stretch')
                else:
                    st.warning("Preview not available.")
                
                notes = st.text_area("Notes (Live)", value=live.get('notes', ''), key=f"note_l_{live['id']}")
                if st.button("Save Notes", key=f"save_l_{live['id']}"):
                    cursor.execute("UPDATE batches SET notes = %s WHERE id = %s", (notes, live['id']))
                    conn.commit()
                    st.success("Notes saved.")

                st.divider()
                if st.button("🔄 Re-sync GitHub", key=f"resync_{live['id']}", disabled=not can_modify, help="Archives the current GitHub file, then re-downloads and pushes the Supabase-deployed version. Use when DB says deployed but GitHub has the wrong file."):
                    with st.spinner("Re-syncing GitHub..."):
                        if perform_repush(target_name, live):
                            st.success(f"✅ GitHub re-synced for {target_name}!")
                            st.rerun()
            else:
                local_path = Path("Gallery UVs") / f"{target_name}.png"
                if local_path.exists():
                    st.warning("⚠️ Unmanaged Legacy File")
                    st.caption("A file exists in your local Gallery UVs folder, but it is not currently tracked by the new database system. It will be automatically tracked when you deploy your first pending batch here.")
                    st.image(str(local_path), width='stretch')
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
                    st.image(p_prev, width='stretch')
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
                        st.image(a_prev, width='stretch')
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
