# pages/stage01_pre_processing.py
import streamlit as st
from pathlib import Path
from PIL import Image
import numpy as np
import imagehash
import sqlite3
from datetime import datetime, timezone
import hashlib
import config

# ---------------- Config ----------------
RAW_DIR = config.RAW_DIR
PROCESSED_DIR = config.CLEANED_DIR
TOLERANCE = config.TOLERANCE
DB_PATH = config.DB_DIR / "image_data.db"

# auto-derive stitched leftovers root
STITCHED_ROOT = PROCESSED_DIR.parent / "3_Stitched"

# ---------------- Helpers ----------------
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

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


def find_raw_record(cursor, img_path, img_hash):
    cursor.execute("""
        SELECT hash FROM raw_image_data
        WHERE modified_hash=? OR hash=? OR original_filename=?
    """, (img_hash, img_hash, img_path.name))
    row = cursor.fetchone()
    return row[0] if row else None


def raw_record_exists(cursor, img_hash):
    cursor.execute("""
        SELECT 1 FROM raw_image_data
        WHERE hash=? OR modified_hash=?
    """, (img_hash, img_hash))
    return cursor.fetchone() is not None


def is_duplicate(cursor, original_hash, phash):
    cursor.execute("""
        SELECT 1 FROM processed_image_data
        WHERE original_hash=? OR phash=?
    """, (original_hash, phash))
    return cursor.fetchone() is not None


# ✅ NEW — check whether duplicate was already stitched before
def already_stitched(filename, original_hash):
    if not STITCHED_ROOT.exists():
        return False

    for f in STITCHED_ROOT.rglob("*"):
        if not f.is_file():
            continue
        name = f.name
        if filename in name or original_hash in name:
            return True
    return False


# ---------------- Leftover Loader ----------------
def collect_leftover_files():
    files = []
    if not STITCHED_ROOT.exists():
        return files

    for folder in STITCHED_ROOT.glob("Leftovers_*"):
        for f in folder.rglob("*"):
            if f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                files.append(f)
    return files


# ---------------- UI ----------------
st.title("Stage 1: Preprocess Raw Images")

include_leftovers = st.toggle("Reintroduce leftover images from previous batches", value=False)

if not RAW_DIR.exists():
    st.warning(f"No raw directory found: {RAW_DIR}")
    st.stop()

raw_files = [f for f in RAW_DIR.iterdir() if f.suffix.lower() in (".png",".jpg",".jpeg")]

if include_leftovers:
    leftovers = collect_leftover_files()
    raw_files.extend(leftovers)
    st.info(f"Including {len(leftovers)} leftover image(s)")

total_raw = len(raw_files)

if total_raw == 0:
    st.warning("No images found to process.")
    st.stop()

st.write(f"Total images queued: {total_raw}")


# ---------------- Processing ----------------
if st.button("Run Stage 1 Processing"):

    conn, cursor = init_db()

    success_count = 0
    skipped_duplicates = 0
    failed = []

    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, path in enumerate(raw_files):

        try:
            data = path.read_bytes()
            img_hash = sha256_bytes(data)
            img_phash = str(imagehash.phash(Image.open(path)))

            linked_hash = find_raw_record(cursor, path, img_hash)
            original_hash = linked_hash or img_hash

            duplicate = is_duplicate(cursor, original_hash, img_phash)

            # ✅ NEW LOGIC BLOCK
            if duplicate:
                if already_stitched(path.name, original_hash):
                    skipped_duplicates += 1
                    progress_bar.progress((i+1)/total_raw)
                    continue
                # else:
                # duplicate exists but not stitched yet → allow through

            if not raw_record_exists(cursor, img_hash):
                cursor.execute("""
                    INSERT INTO raw_image_data
                    (hash, phash, original_filename, created_at, processing)
                    VALUES (?, ?, ?, ?, 0)
                """, (
                    img_hash,
                    img_phash,
                    path.name,
                    datetime.now(timezone.utc).isoformat()
                ))

            image = Image.open(path)

            if image.mode == 'RGBA':
                image = image.convert('RGB')

            arr = np.array(image)

            mask = np.all(arr > TOLERANCE, axis=-1)
            coords = np.argwhere(mask)

            if coords.size == 0:
                failed.append(path.name)
                continue

            y0, x0 = coords.min(axis=0)
            y1, x1 = coords.max(axis=0) + 1

            cropped = (
                image.crop((x0,y0,x1,y1))
                if (x1-x0 < image.width*0.95 or y1-y0 < image.height*0.95)
                else image
            )

            w,h = cropped.size
            ratio = w/h

            if ratio < 0.6: category="Extra Tall"
            elif ratio < 0.9: category="Portrait"
            elif ratio <= 1.1: category="Square"
            elif ratio <= 1.8: category="Landscape"
            else: category="Extra Wide"

            sizes = {
                "Square":(512,512),
                "Portrait":(512,717),
                "Extra Tall":(512,1024),
                "Landscape":(717,512),
                "Extra Wide":(1024,512)
            }

            target_w,target_h = sizes[category]
            resized = cropped.resize((target_w,target_h), Image.Resampling.LANCZOS)

            output_dir = PROCESSED_DIR / category
            output_dir.mkdir(parents=True, exist_ok=True)

            out_path = output_dir / path.name
            resized.save(out_path)

            processed_hash = sha256_bytes(out_path.read_bytes())
            processed_phash = str(imagehash.phash(resized))

            cursor.execute("""
                INSERT INTO processed_image_data (
                    hash, phash, original_hash, original_filename,
                    category, width, height, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                processed_hash,
                processed_phash,
                original_hash,
                path.name,
                category,
                target_w,
                target_h,
                datetime.now(timezone.utc).isoformat()
            ))

            cursor.execute(
                "UPDATE raw_image_data SET processing=1 WHERE hash=?",
                (original_hash,)
            )

            # ---------- Delete source file AFTER success ----------
            try:
                path.unlink()
            except Exception as cleanup_err:
                print(f"Cleanup warning for {path}: {cleanup_err}")

            success_count += 1

        except Exception as e:
            failed.append(path.name)
            print(f"Error processing {path.name}: {e}")

        progress_bar.progress((i+1)/total_raw)
        status_text.text(f"Processed {i+1}/{total_raw}")
        conn.commit()

    # ---------------- Summary ----------------
    st.success("Processing complete")

    st.write(f"Total input images: {total_raw}")
    st.write(f"Processed successfully: {success_count}")
    st.write(f"Duplicates skipped: {skipped_duplicates}")
    st.write(f"Failed: {len(failed)}")

    if failed:
        st.warning("Failed images:")
        st.write(failed)

    conn.close()