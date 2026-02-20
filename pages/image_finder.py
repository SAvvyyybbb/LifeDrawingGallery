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
st.title("LifeDrawingGallery — Image Finder / Hash Inspector")
st.write("""
Search images in your database by SHA256 hash, modified hash, phash, or original filename.
Preview the image and see which folder it resides in.
""")

# ---------------- Inputs ----------------
hash_input = st.text_input("Enter SHA256 hash or modified hash")
filename_input = st.text_input("Enter filename (partial match OK)")
phash_input = st.text_input("Enter phash (hex) for visual similarity")
tolerance = st.slider("Phash similarity tolerance (Hamming distance)", 0, 10, 5)

# ---------------- Helpers ----------------
def init_db(db_path):
    if not db_path.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    return conn, conn.cursor()

def find_similar_phash(cursor, input_phash_hex, tol=5):
    results = []
    try:
        input_phash = imagehash.hex_to_hash(input_phash_hex)
    except Exception:
        st.warning("Invalid phash format")
        return results

    cursor.execute("SELECT hash, phash, original_filename FROM raw_image_data")
    for row in cursor.fetchall():
        db_phash_hex = row[1]
        if not db_phash_hex:
            continue
        db_phash = imagehash.hex_to_hash(db_phash_hex)
        if input_phash - db_phash <= tol:
            results.append(row)
    return results

def display_image_from_hash(img_hash):
    for folder in [config.RAW_DIR, config.CLEANED_DIR, config.IMAGE_PROCESSING_DIR]:
        # Try common extensions
        for ext in [".jpg", ".png", ".jpeg"]:
            path = folder / f"{img_hash}{ext}"
            if path.exists():
                img = Image.open(path)
                img = ImageOps.exif_transpose(img)
                st.image(img, caption=f"{img_hash} — {folder.name}", use_column_width=True)
                st.write(f"Folder: `{folder}`")
                return
    st.warning("Image file not found in any folder")

# ---------------- Search ----------------
if st.button("Search"):
    conn, cursor = init_db(config.DB_DIR / "image_data.db")
    results = []

    # search by hash
    if hash_input:
        cursor.execute(
            "SELECT * FROM raw_image_data WHERE hash=? OR modified_hash=?",
            (hash_input, hash_input)
        )
        results.extend(cursor.fetchall())

    # search by filename
    if filename_input:
        cursor.execute(
            "SELECT * FROM raw_image_data WHERE original_filename LIKE ?",
            (f"%{filename_input}%",)
        )
        results.extend(cursor.fetchall())

    # search by phash
    if phash_input:
        phash_matches = find_similar_phash(cursor, phash_input, tol=tolerance)
        for r in phash_matches:
            cursor.execute(
                "SELECT * FROM raw_image_data WHERE hash=?",
                (r[0],)
            )
            row = cursor.fetchone()
            if row:
                results.append(row)

    # remove duplicates
    results = list({r[0]: r for r in results}.values())

    if results:
        st.success(f"Found {len(results)} match(es)")
        for r in results:
            st.json({
                "hash": r[0],
                "modified_hash": r[1],
                "phash": r[2],
                "poster_id": r[3],
                "poster_name": r[4],
                "message_id": r[5],
                "channel_id": r[6],
                "original_filename": r[7],
                "created_at": r[8],
                "processing": r[9],
                "batched": r[10]
            })
            display_image_from_hash(r[0])
    else:
        st.info("No matches found")
    conn.close()