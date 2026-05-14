# Streamlit Home Page
import streamlit as st
import pandas as pd
import io
import config
from PIL import Image
from streamlit_autorefresh import st_autorefresh

def run_home():
    # Auto-refresh every 30 seconds
    st_autorefresh(interval=30 * 1000, key="datarefresh")

    # ---------------- Database Connection ----------------
    try:
        conn = config.get_db_connection()
        cursor = conn.cursor()
    except Exception as e:
        st.error(f"Failed to connect to cloud database: {e}")
        return

    try:
        # ---------------- Fetch Metrics (single round-trip) ----------------
        cursor.execute("""
            SELECT
                (SELECT COUNT(*) FROM raw_image_data WHERE veto = 0) AS total_raw,
                (SELECT COUNT(*) FROM raw_image_data WHERE veto = 0 AND processing = 0 AND storage_key_raw IS NOT NULL) AS pending_processing,
                (SELECT COUNT(*) FROM processed_image_data) AS total_cleaned,
                (SELECT COUNT(*) FROM images WHERE is_stitched = 1) AS total_stitched
        """)
        row = cursor.fetchone()
        total_raw, pending_processing, total_cleaned, total_stitched = row

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
            3. **Stage 01 (Pre-Processing):** Run Stage 01 via the Manual Scraper or a separate background script.
            4. **1: Batch Manager:** Intelligent grouping by Aspect Ratio and Hue.
            5. **2: Stitching & Validation:** Create UV maps and review arrangement.
            6. **3: Final Audit & Deploy:** Side-by-side comparison and GitHub push.
            """)

        with col_ctrl:
            st.subheader("⚙️ Management")
            if st.button("Restart Discord Bot", use_container_width=True):
                import subprocess
                import sys
                with st.spinner("Restarting bot..."):
                    subprocess.run('pkill -9 -f "[d]iscord_scraper.py"', shell=True)
                    python_exe = sys.executable
                    subprocess.Popen([python_exe, 'discord_scraper.py'],
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL,
                                     start_new_session=True)
                st.success("✅ Bot restart command issued!")

        st.divider()

        # ---------------- Recent Cleaned Images Preview ----------------
        st.subheader("✨ Recent Cleaned Images")
        cursor.execute("""
            SELECT storage_key_processed, category
            FROM processed_image_data
            WHERE storage_key_processed IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 12
        """)
        recent_cleaned = cursor.fetchall()

        if recent_cleaned:
            cols = st.columns(6)
            for i, row in enumerate(recent_cleaned):
                storage_key, category = row
                with cols[i % 6]:
                    try:
                        data = config.supabase_storage_client.storage.from_("cleaned_images").download(storage_key)
                        thumb = Image.open(io.BytesIO(data))
                        thumb.thumbnail((150, 150))
                        st.image(thumb, caption=f"{category}", use_container_width=True)
                    except:
                        pass

    finally:
        conn.close()

if __name__ == "__main__":
    st.set_page_config(page_title="LifeDrawingGallery Manager", layout="wide")
    run_home()
