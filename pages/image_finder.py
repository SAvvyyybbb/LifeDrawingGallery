# pages/image_finder.py
import streamlit as st
from pathlib import Path
from PIL import Image, ImageOps
import config
from psycopg2.extras import RealDictCursor
import pandas as pd

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="Image Finder",
    layout="wide"
)

st.title("🔍 Image Explorer")
st.write("Browse and filter all images in the cloud database.")

# ---------------- Database Connection ----------------
try:
    conn = config.get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
except Exception as e:
    st.error(f"Failed to connect to cloud database: {e}")
    st.stop()

# ---------------- Caching ----------------
@st.cache_data(show_spinner=False, ttl=600)
def get_filter_options():
    cursor.execute("SELECT DISTINCT poster_name FROM raw_image_data WHERE poster_name IS NOT NULL ORDER BY poster_name")
    posters = [r['poster_name'] for r in cursor.fetchall()]
    
    cursor.execute("SELECT DISTINCT content_category FROM raw_image_data WHERE content_category IS NOT NULL ORDER BY content_category")
    categories = [r['content_category'] for r in cursor.fetchall()]
    
    return posters, categories

posters, categories = get_filter_options()

# ---------------- Sidebar Filters ----------------
with st.sidebar:
    st.title("🎯 Filters")
    
    search_q = st.text_input("Search (Filename/Hash/User)", help="Partial matches allowed for filename and poster name.")
    
    sel_poster = st.selectbox("Filter by Submitter", ["All"] + posters)
    sel_cat = st.selectbox("Filter by Category", ["All"] + categories)
    
    sel_status = st.selectbox("Status", ["All", "Never Batched", "In Pending Batch", "Stitched & Validated"])
    
    sel_veto = st.radio("Veto Status", ["Art Only", "Vetoed Only", "Both"])

# ---------------- Query Building ----------------
query = """
    SELECT 
        r.hash, r.storage_key_raw, r.original_filename, r.poster_name, r.content_category, r.created_at, r.veto,
        i.batch_id, b.status as batch_status, b.batch_name
    FROM raw_image_data r
    LEFT JOIN images i ON r.hash = i.hash
    LEFT JOIN batches b ON i.batch_id = b.id
    WHERE 1=1
"""
params = []

if search_q:
    query += " AND (lower(r.original_filename) LIKE %s OR lower(r.hash) LIKE %s OR lower(r.poster_name) LIKE %s)"
    search_param = f"%{search_q.lower()}%"
    params.extend([search_param, search_param, search_param])

if sel_poster != "All":
    query += " AND r.poster_name = %s"
    params.append(sel_poster)

if sel_cat != "All":
    query += " AND r.content_category = %s"
    params.append(sel_cat)

if sel_veto == "Art Only":
    query += " AND r.veto = 0"
elif sel_veto == "Vetoed Only":
    query += " AND r.veto = 1"

if sel_status == "Never Batched":
    query += " AND i.id IS NULL"
elif sel_status == "In Pending Batch":
    query += " AND i.id IS NOT NULL AND (b.status != 'validated' OR b.status IS NULL)"
elif sel_status == "Stitched & Validated":
    query += " AND b.status = 'validated'"

query += " ORDER BY r.created_at DESC LIMIT 200"

cursor.execute(query, params)
results = cursor.fetchall()

# ---------------- UI Display ----------------
st.subheader(f"Results ({len(results)} matches)")

if not results:
    st.info("No images match your current filters.")
else:
    # Display in a grid
    cols = st.columns(4)
    for i, r in enumerate(results):
        with cols[i % 4]:
            # Thumbnail Logic
            # We'll try to find processed if available, otherwise raw
            # But for search, raw is fine
            image_url = f"{config.SUPABASE_URL}/storage/v1/object/public/raw_images/{r['storage_key_raw']}"
            
            # Use container for grouping
            with st.container(border=True):
                st.image(image_url, width="stretch")
                
                name = r['original_filename'] or "Untitled"
                st.write(f"**{name[:25]}...**")
                
                # Badges
                status_color = "green" if r['batch_status'] == 'validated' else ("blue" if r['batch_id'] else "orange")
                status_text = "Stitched" if r['batch_status'] == 'validated' else ("Batched" if r['batch_id'] else "Unbatched")
                
                col1, col2 = st.columns(2)
                col1.markdown(f":{status_color}[{status_text}]")
                if r['veto']: col2.markdown(":red[VETOED]")
                
                st.caption(f"👤 {r['poster_name']}")
                st.caption(f"📅 {r['created_at'].strftime('%Y-%m-%d')}")
                
                with st.expander("More Info"):
                    st.write(f"**Category:** {r['content_category']}")
                    st.write(f"**Hash:** `{r['hash'][:12]}...`")
                    if r['batch_id']:
                        st.write(f"**Batch:** {r['batch_name']} (ID: {r['batch_id']})")

conn.close()
