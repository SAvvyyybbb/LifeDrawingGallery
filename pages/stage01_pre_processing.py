import streamlit as st
from pathlib import Path
from PIL import Image
import numpy as np
<<<<<<< HEAD
import imagehash
import sqlite3
from datetime import datetime, timezone
import hashlib
import config
=======
import config  # import centralized config
>>>>>>> 8bf44ef04b181bc2f2ad841cd166aab13476240f

# ---------------- Config ----------------
RAW_DIR = config.RAW_DIR
PROCESSED_DIR = config.CLEANED_DIR
TOLERANCE = config.TOLERANCE
<<<<<<< HEAD
DB_PATH = config.DB_DIR / "image_data.db"

# ---------------- Helpers ----------------
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def normalize_extension(ext: str) -> str:
    ext = ext.lower()
    return ".jpg" if ext == ".jpeg" else ext

def init_db():
    """Initialize DB and ensure tables exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Raw images table
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

    # Processed images table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_image_data (
            hash TEXT PRIMARY KEY,
            phash TEXT,
            original_hash TEXT,
            original_filename TEXT,
            category TEXT,
            width INTEGER,
            height INTEGER,
            created_at TEXT
        )
    """)

    conn.commit()
    return conn, cursor

def find_raw_record(cursor, raw_hash, filename):
    """Find raw record by hash or fallback to filename."""
    cursor.execute(
        "SELECT hash FROM raw_image_data WHERE hash=? OR original_filename=?",
        (raw_hash, filename)
    )
    row = cursor.fetchone()
    return row[0] if row else None

# ---------------- Streamlit UI ----------------
st.title("Stage 0: Preprocess Raw Images (Optional)")

=======

# ---------------- Page UI ----------------
st.title("Stage 0: Preprocess Raw Images (Optional)")

# Scan Raw folder
>>>>>>> 8bf44ef04b181bc2f2ad841cd166aab13476240f
raw_files = [f for f in RAW_DIR.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg")]
total_raw = len(raw_files)
st.write(f"Found {total_raw} image(s) in Raw folder.")

if total_raw == 0:
    st.info("No images found in Raw folder. Stage 0 skipped.")
else:
    if st.button("Run Stage 0: Process Raw Images"):
<<<<<<< HEAD
        conn, cursor = init_db()
=======
>>>>>>> 8bf44ef04b181bc2f2ad841cd166aab13476240f
        success_count = 0
        failed = []

        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, path in enumerate(raw_files):
            try:
<<<<<<< HEAD
                data = path.read_bytes()
                raw_hash = sha256_bytes(data)
                raw_phash = str(imagehash.phash(Image.open(path)))

                # ---------------- Skip if already processed ----------------
                cursor.execute(
                    "SELECT processing FROM raw_image_data WHERE hash=?",
                    (raw_hash,)
                )
                row = cursor.fetchone()
                if row and row[0] == 1:
                    status_text.text(f"Skipping {path.name} (already processed)")
                    progress_bar.progress((i+1)/total_raw)
                    continue

                # ---------------- Log raw image if not exists ----------------
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO raw_image_data 
                    (hash, phash, original_filename, created_at, processing)
                    VALUES (?, ?, ?, ?, 0)
                    """,
                    (raw_hash, raw_phash, path.name, datetime.now(timezone.utc).isoformat())
                )

                # ---------------- Process image ----------------
=======
>>>>>>> 8bf44ef04b181bc2f2ad841cd166aab13476240f
                image = Image.open(path)
                if image.mode == 'RGBA':
                    image = image.convert('RGB')
                arr = np.array(image)

<<<<<<< HEAD
                # Remove black borders
=======
                # ---------------- Remove black borders ----------------
>>>>>>> 8bf44ef04b181bc2f2ad841cd166aab13476240f
                mask = np.all(arr > TOLERANCE, axis=-1)
                coords = np.argwhere(mask)
                if coords.size == 0:
                    failed.append(path.name)
                    continue
                y0, x0 = coords.min(axis=0)
                y1, x1 = coords.max(axis=0) + 1
                cropped = image.crop((x0, y0, x1, y1)) \
                    if (x1-x0 < image.width*0.95 or y1-y0 < image.height*0.95) else image

<<<<<<< HEAD
                # Aspect ratio classification
=======
                # ---------------- Aspect ratio classification ----------------
>>>>>>> 8bf44ef04b181bc2f2ad841cd166aab13476240f
                w, h = cropped.size
                ratio = w/h
                if ratio < 0.6: category = "Extra Tall"
                elif 0.6 <= ratio < 0.9: category = "Portrait"
                elif 0.9 <= ratio <= 1.1: category = "Square"
                elif 1.1 < ratio <= 1.8: category = "Landscape"
                else: category = "Extra Wide"

<<<<<<< HEAD
                # Resize
=======
                # ---------------- Resize to category dimensions ----------------
>>>>>>> 8bf44ef04b181bc2f2ad841cd166aab13476240f
                sizes = {
                    "Square": (512,512),
                    "Portrait": (512,717),
                    "Extra Tall": (512,1024),
                    "Landscape": (717,512),
                    "Extra Wide": (1024,512)
                }
                target_w, target_h = sizes[category]
                resized = cropped.resize((target_w,target_h), Image.Resampling.LANCZOS)

<<<<<<< HEAD
                # Save to processed folder
=======
                # ---------------- Save to Processed folder ----------------
>>>>>>> 8bf44ef04b181bc2f2ad841cd166aab13476240f
                output_dir = PROCESSED_DIR / category
                output_dir.mkdir(parents=True, exist_ok=True)
                out_path = output_dir / path.name
                resized.save(out_path)
<<<<<<< HEAD

                # Compute processed hash/phash
                processed_hash = sha256_bytes(out_path.read_bytes())
                processed_phash = str(imagehash.phash(resized))

                # Link to raw_image_data
                linked_hash = find_raw_record(cursor, raw_hash, path.name)

                # Insert into processed_image_data
                cursor.execute(
                    """
                    INSERT INTO processed_image_data (
                        hash, phash, original_hash, original_filename,
                        category, width, height, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (processed_hash, processed_phash, linked_hash, path.name,
                     category, target_w, target_h, datetime.now(timezone.utc).isoformat())
                )

                # Update raw processing flag
                if linked_hash:
                    cursor.execute(
                        "UPDATE raw_image_data SET processing=1 WHERE hash=?",
                        (linked_hash,)
                    )

                # Delete raw file
                path.unlink()
=======
                path.unlink()  # remove original raw image
>>>>>>> 8bf44ef04b181bc2f2ad841cd166aab13476240f
                success_count += 1

            except Exception as e:
                failed.append(path.name)
                print(f"Error processing {path.name}: {e}")

            # Update progress
            progress_bar.progress((i+1)/total_raw)
            status_text.text(f"Processed {i+1}/{total_raw} images...")

<<<<<<< HEAD
            conn.commit()

=======
>>>>>>> 8bf44ef04b181bc2f2ad841cd166aab13476240f
        # ---------------- Summary ----------------
        st.success("Stage 0 processing complete!")
        st.write(f"Total images in Raw folder: {total_raw}")
        st.write(f"Successfully processed: {success_count}")
        st.write(f"Failed images: {len(failed)}")
        if failed:
            st.warning("Failed images:")
            st.write(failed)
<<<<<<< HEAD

        conn.close()
=======
>>>>>>> 8bf44ef04b181bc2f2ad841cd166aab13476240f
