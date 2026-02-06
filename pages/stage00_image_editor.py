import streamlit as st
from pathlib import Path
from PIL import Image
import numpy as np
import imagehash
import sqlite3
import hashlib
from datetime import datetime, timezone
import config

# ---------------- Config ----------------
RAW_DIR = config.RAW_DIR
PROCESSED_DIR = config.CLEANED_DIR
DB_PATH = config.DB_DIR / "image_data.db"
TOLERANCE = config.TOLERANCE

# ---------------- Helpers ----------------
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def normalize_extension(ext: str) -> str:
    ext = ext.lower()
    if ext == ".jpeg":
        return ".jpg"
    return ext

def init_db():
    """Initialize DB and tables for Stage 0 processing."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Table for raw image ingestion
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_image_data (
            hash TEXT PRIMARY KEY,
            phash TEXT,
            poster_id INTEGER,
            poster_name TEXT,
            message_id INTEGER,
            channel_id INTEGER,
            original_filename TEXT,
            created_at TEXT,
            processing INTEGER DEFAULT 0,
            batched INTEGER DEFAULT 0
        )
    """)

    # Table for processed images
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_image_data (
            hash TEXT PRIMARY KEY,
            phash TEXT,
            original_hash TEXT,
            category TEXT,
            width INTEGER,
            height INTEGER,
            created_at TEXT
        )
    """)

    conn.commit()
    return conn, cursor

# ---------------- Page UI ----------------
st.title("Stage 0: Preprocess Raw Images (Optional)")

raw_files = [f for f in RAW_DIR.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg")]
total_raw = len(raw_files)
st.write(f"Found {total_raw} image(s) in Raw folder.")

if total_raw == 0:
    st.info("No images found in Raw folder. Stage 0 skipped.")
else:
    if st.button("Run Stage 0: Process Raw Images"):
        conn, cursor = init_db()
        success_count = 0
        failed = []

        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, path in enumerate(raw_files):
            try:
                data = path.read_bytes()
                original_hash = sha256_bytes(data)
                image = Image.open(path)
                if image.mode == 'RGBA':
                    image = image.convert('RGB')
                original_phash = imagehash.phash(image)

                # ---------------- Log raw image ----------------
                cursor.execute("""
                    INSERT OR IGNORE INTO raw_image_data (hash, phash, created_at, processing)
                    VALUES (?, ?, ?, 0)
                """, (original_hash, str(original_phash), datetime.now(timezone.utc).isoformat()))

                # ---------------- Remove black borders ----------------
                arr = np.array(image)
                mask = np.all(arr > TOLERANCE, axis=-1)
                coords = np.argwhere(mask)
                if coords.size == 0:
                    failed.append(path.name)
                    continue
                y0, x0 = coords.min(axis=0)
                y1, x1 = coords.max(axis=0) + 1
                cropped = image.crop((x0, y0, x1, y1)) \
                    if (x1-x0 < image.width*0.95 or y1-y0 < image.height*0.95) else image

                # ---------------- Aspect ratio classification ----------------
                w, h = cropped.size
                ratio = w/h
                if ratio < 0.6: category = "Extra Tall"
                elif 0.6 <= ratio < 0.9: category = "Portrait"
                elif 0.9 <= ratio <= 1.1: category = "Square"
                elif 1.1 < ratio <= 1.8: category = "Landscape"
                else: category = "Extra Wide"

                # ---------------- Resize ----------------
                sizes = {
                    "Square": (512,512),
                    "Portrait": (512,717),
                    "Extra Tall": (512,1024),
                    "Landscape": (717,512),
                    "Extra Wide": (1024,512)
                }
                target_w, target_h = sizes[category]
                resized = cropped.resize((target_w,target_h), Image.Resampling.LANCZOS)

                # ---------------- Save processed image ----------------
                output_dir = PROCESSED_DIR / category
                output_dir.mkdir(parents=True, exist_ok=True)
                out_path = output_dir / path.name
                resized.save(out_path)
                path.unlink()  # remove raw image

                # ---------------- Log processed image ----------------
                processed_hash = sha256_bytes(resized.tobytes())
                processed_phash = imagehash.phash(resized)
                cursor.execute("""
                    INSERT OR REPLACE INTO processed_image_data (
                        hash, phash, original_hash, category, width, height, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    processed_hash, str(processed_phash), original_hash,
                    category, resized.width, resized.height,
                    datetime.now(timezone.utc).isoformat()
                ))

                # ---------------- Update processing flag ----------------
                cursor.execute("""
                    UPDATE raw_image_data
                    SET processing=1
                    WHERE hash=?
                """, (original_hash,))

                conn.commit()
                success_count += 1

            except Exception as e:
                failed.append(path.name)
                print(f"Error processing {path.name}: {e}")

            progress_bar.progress((i+1)/total_raw)
            status_text.text(f"Processed {i+1}/{total_raw} images...")

        st.success("Stage 0 processing complete!")
        st.write(f"Total images: {total_raw}")
        st.write(f"Successfully processed: {success_count}")
        st.write(f"Failed images: {len(failed)}")
        if failed:
            st.warning("Failed images:")
            st.write(failed)
        conn.close()
