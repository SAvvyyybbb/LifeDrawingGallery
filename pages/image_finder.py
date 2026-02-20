# pages/image_finder.py
import streamlit as st
from pathlib import Path
from PIL import Image, ImageOps
import sqlite3
import imagehash
import config

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="Image Finder",
    layout="wide"
)

st.title("LifeDrawingGallery — Image Finder")
st.write("""
Search your database for images by **SHA256 hash**, **phash**, **modified_hash**, or **original filename**.  
The matching image (if found) will display along with its folder.
""")

# ---------------- Helpers ----------------
DB_PATH = config.DB_DIR / "image_data.db"

def init_db():
    if not DB_PATH.exists():
        st.error(f"Database not found at `{DB_PATH}`")
        return None, None
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    return conn, cursor

def find_images(cursor, query):
    query_lower = query.lower()
    # exact match for hash fields or filename
    cursor.execute("""
        SELECT hash, phash, modified_hash, poster_id, poster_name, message_id, channel_id, original_filename
        FROM raw_image_data
        WHERE
            lower(hash)=? OR
            lower(phash)=? OR
            lower(modified_hash)=? OR
            lower(original_filename)=?
    """, (query_lower, query_lower, query_lower, query_lower))
    return cursor.fetchall()

def display_image_from_filename(original_filename):
    """Search all relevant folders for a file matching the original filename and display it."""
    found = False
    filename_lower = original_filename.lower()
    for folder in [config.RAW_DIR, config.CLEANED_DIR, config.IMAGE_PROCESSING_DIR]:
        for path in folder.rglob("*"):
            if path.is_file() and path.name.lower() == filename_lower:
                img = Image.open(path)
                img = ImageOps.exif_transpose(img)
                st.image(img, caption=f"{path.name} — {folder.name}", use_column_width=True)
                st.write(f"Folder: `{folder}`")
                found = True
                break
        if found:
            break
    if not found:
        st.warning(f"Image file `{original_filename}` not found in any folder")

# ---------------- UI ----------------
search_query = st.text_input("Enter SHA256 hash, phash, modified_hash, or original filename")

if search_query:
    conn, cursor = init_db()
    if conn and cursor:
        results = find_images(cursor, search_query)
        if not results:
            st.warning("No results found in database.")
        else:
            st.success(f"Found {len(results)} record(s) in database.")
            for r in results:
                st.markdown("---")
                st.write(f"**Original Filename:** {r[7]}")
                st.write(f"**Hash:** {r[0]}")
                st.write(f"**Phash:** {r[1]}")
                st.write(f"**Modified Hash:** {r[2]}")
                st.write(f"**Poster ID:** {r[3]}")
                st.write(f"**Poster Name:** {r[4]}")
                st.write(f"**Message ID:** {r[5]}")
                st.write(f"**Channel ID:** {r[6]}")

                # Display image from folders by original filename
                display_image_from_filename(r[7])

        conn.close()