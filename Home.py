# Streamlit_booter.py
import streamlit as st
import pandas as pd
import config
from PIL import Image
from streamlit_autorefresh import st_autorefresh

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="LifeDrawingGallery Manager",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Auto-refresh every 30 seconds
st_autorefresh(interval=30 * 1000, key="datarefresh")

# ---------------- Database Connection ----------------
try:
    conn = config.get_db_connection()
    cursor = conn.cursor()
except Exception as e:
    st.error(f"Failed to connect to cloud database: {e}")
    st.stop()

# ---------------- Fetch Metrics ----------------
# Total Scraped (Raw)
cursor.execute("SELECT COUNT(*) FROM raw_image_data WHERE veto = 0")
total_raw = cursor.fetchone()[0]

# Pending Stage 1
cursor.execute("SELECT COUNT(*) FROM raw_image_data WHERE veto = 0 AND processing = 0 AND storage_key_raw IS NOT NULL")
pending_processing = cursor.fetchone()[0]

# Total Cleaned
cursor.execute("SELECT COUNT(*) FROM processed_image_data")
total_cleaned = cursor.fetchone()[0]

# Batched / Stitched
cursor.execute("SELECT COUNT(*) FROM images WHERE is_stitched = 1")
total_stitched = cursor.fetchone()[0]

# ---------------- Caching ----------------
@st.cache_data(show_spinner=False, max_entries=200)
def get_dashboard_thumbnail(storage_key):
    """Downloads and caches thumbnails for the dashboard."""
    preview_cache_dir = config.IMAGE_PROCESSING_DIR / "preview_cache"
    preview_cache_dir.mkdir(exist_ok=True)
    local_path = preview_cache_dir / storage_key
    
    if not local_path.exists():
        config.download_from_supabase(storage_key, preview_cache_dir, "cleaned_images")
    
    if local_path.exists():
        try:
            thumb = Image.open(local_path)
            thumb.thumbnail((150, 150))
            return thumb
        except:
            return None
    return None

# ---------------- UI Layout ----------------
st.title("🎨 LifeDrawingGallery Manager")
st.markdown("Welcome to the unified cloud-powered pipeline for collecting, processing, and deploying artwork.")
st.divider()

# ---------------- Pipeline Health ----------------
st.subheader("🚀 Pipeline Health")
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Scraped", total_raw)
with col2:
    st.metric("Pending Clean", pending_processing, delta_color="inverse")
with col3:
    st.metric("Total Cleaned", total_cleaned)
with col4:
    st.metric("Total Stitched", total_stitched)

if pending_processing > 0:
    st.write(f"**Clean Queue:** {pending_processing} images awaiting Stage 1.")
    progress_val = min(1.0, 1.0 - (pending_processing / max(1, total_raw)))
    st.progress(progress_val)
    st.caption("Auto-refreshes as background workers finish tasks.")

st.divider()

# ---------------- Main Dashboard Area ----------------
col_workflow, col_ctrl = st.columns([2, 1])

with col_workflow:
    st.subheader("📚 Workflow Guide")
    
    st.markdown("""
    1. **Discord Bot:** Runs in the background, downloading new submissions to the `raw_images` bucket.
    2. **0: Image Editor:** Manually crop selfies or triage images flagged by the auto-processor.
    3. **Stage 01 (Pre-Processing):** Run `python3 process_stage1.py` in your terminal to auto-crop/resize images.
    4. **1: Batch Manager:** Intelligent grouping by Aspect Ratio and Hue.
    5. **2: Stitching & Validation:** Create UV maps and review arrangement.
    6. **3: Final Audit & Deploy:** Side-by-side comparison and GitHub push.
    """)
    
    with st.expander("❓ Troubleshooting"):
        st.markdown("""
        **Slash commands (/my_submissions) missing?**
        - Wait: Discord can take up to an hour to sync new global commands.
        - Restart: Use the "Restart Discord Bot" button on this page.
        
        **App taking a long time to load?**
        - Look for the **loading spinner** in the top right. Communication with cloud DB/Storage can take a few seconds.
        """)

with col_ctrl:
    st.subheader("⚙️ Management")
    if st.button("Restart Discord Bot", width='stretch'):
        import subprocess
        import os
        import sys
        with st.spinner("Restarting bot..."):
            subprocess.run('pkill -9 -f "[d]iscord_scraper.py"', shell=True)
            python_exe = "./venv/bin/python" if os.path.exists("./venv/bin/python") else sys.executable
            subprocess.Popen([python_exe, 'discord_scraper.py'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setpgrp if os.name != 'nt' else None)
        st.success("✅ Bot restart command issued!")

st.divider()

# ---------------- Recent Cleaned Images Preview ----------------
st.subheader("✨ Recent Cleaned Images")

cursor.execute("""
    SELECT storage_key_processed, original_filename, category 
    FROM processed_image_data 
    WHERE storage_key_processed IS NOT NULL
    ORDER BY created_at DESC 
    LIMIT 12
""")
recent_cleaned = cursor.fetchall()

if recent_cleaned:
    config.CLEANED_DIR.mkdir(parents=True, exist_ok=True)
    cols = st.columns(6)
    for i, row in enumerate(recent_cleaned):
        storage_key, filename, category = row
        with cols[i % 6]:
            thumb = get_dashboard_thumbnail(storage_key)
            if thumb:
                st.image(thumb, caption=f"{category}", width="stretch")

conn.close()
