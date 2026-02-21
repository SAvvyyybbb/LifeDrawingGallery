from pathlib import Path
from PIL import Image
import imagehash
import numpy as np
import sqlite3
from datetime import datetime
import os
import streamlit as st
import pandas as pd
import hashlib
import config

OUTPUT_SIZE = 2048

# ---------------- Config ----------------
CLEANED_DIR = config.CLEANED_DIR
DB_PATH = config.DB_PATH


# ---------------- Helpers ----------------
def compute_aspect_category(w, h):
    ratio = w / h
    if ratio < 0.6:
        return "Extra Tall"
    elif 0.6 <= ratio < 0.9:
        return "Portrait"
    elif 0.9 <= ratio <= 1.1:
        return "Square"
    elif 1.1 < ratio <= 1.8:
        return "Landscape"
    else:
        return "Extra Wide"


def compute_tile_size(category, w, h):
    if category == "Square":
        tiles = 4
        tile_w = OUTPUT_SIZE // tiles
        tile_h = OUTPUT_SIZE // tiles
        batch_capacity = tiles * tiles

    elif category in ["Landscape", "Extra Wide"]:
        tile_h = OUTPUT_SIZE // 4
        tile_w = w
        cols = OUTPUT_SIZE // tile_w
        rows = OUTPUT_SIZE // tile_h
        batch_capacity = max(1, cols * rows)

    elif category in ["Portrait", "Extra Tall"]:
        tile_w = OUTPUT_SIZE // 4
        tile_h = h
        cols = OUTPUT_SIZE // tile_w
        rows = OUTPUT_SIZE // tile_h
        batch_capacity = max(1, cols * rows)

    else:
        tile_w, tile_h = w, h
        batch_capacity = 1

    return tile_w, tile_h, batch_capacity


def compute_file_hash(file_path: Path):
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


# ---------------- Database Initialization ----------------
def init_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        primary_folder TEXT,
        secondary_folder TEXT,
        status TEXT,
        img_w INTEGER,
        img_h INTEGER,
        expected_count INTEGER,
        batch_name TEXT,
        timestamp TEXT
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id INTEGER,
        veto_ind INTEGER,
        file_path TEXT,
        is_stitched INTEGER DEFAULT 0,
        aspect_category TEXT,
        manual_order INTEGER,
        img_w INTEGER,
        img_h INTEGER,
        avg_r REAL,
        avg_g REAL,
        avg_b REAL,
        perceptual_hash TEXT,
        hash TEXT UNIQUE,
        FOREIGN KEY(batch_id) REFERENCES batches(id)
    )
    """)

    conn.commit()
    return conn


# ---------------- Reset Tables Each Run ----------------
def reset_tables(conn):
    c = conn.cursor()

    c.execute("DELETE FROM batches")
    c.execute("DELETE FROM images")

    c.execute("DELETE FROM sqlite_sequence WHERE name='batches'")
    c.execute("DELETE FROM sqlite_sequence WHERE name='images'")

    conn.commit()


# ---------------- Image Processing ----------------
def process_images(input_dir: Path, conn: sqlite3.Connection):
    c = conn.cursor()

    image_count = 0
    batch_count = 0
    validation_issues = []

    for root, _, files in os.walk(input_dir):

        imgs = [f for f in files if f.lower().endswith((".png", ".jpg", ".jpeg"))]
        if not imgs:
            continue

        rel_path = Path(root).relative_to(input_dir)
        parts = rel_path.parts

        primary_folder = parts[0] if len(parts) > 0 else "root"
        secondary_folder = parts[1] if len(parts) > 1 else None

        img_metadata = []
        aspect_set = set()

        for f in imgs:

            abs_path = str((Path(root) / f).resolve())

            try:
                img = Image.open(abs_path).convert("RGB")
                w, h = img.size
                category = compute_aspect_category(w, h)

                arr = np.array(img)
                avg_r, avg_g, avg_b = arr[:,:,0].mean(), arr[:,:,1].mean(), arr[:,:,2].mean()

                perceptual_hash = str(imagehash.phash(img))
                file_hash = compute_file_hash(Path(abs_path))

                # ----- INSERT (hash prevents duplicates) -----
                c.execute("""
                    INSERT OR IGNORE INTO images
                    (file_path, aspect_category, img_w, img_h,
                     avg_r, avg_g, avg_b, perceptual_hash, hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (abs_path, category, w, h,
                      avg_r, avg_g, avg_b, perceptual_hash, file_hash))

                image_count += 1

                img_metadata.append({
                    "file_path": abs_path,
                    "w": w,
                    "h": h,
                    "category": category,
                    "avg": (avg_r+avg_g+avg_b)/3
                })

                aspect_set.add(category)

            except Exception as e:
                print(f"Skipping {abs_path}: {e}")
                continue

        if len(aspect_set) > 1:
            validation_issues.append((str(rel_path), list(aspect_set)))

        if not img_metadata:
            continue

        # ---------- SORT ----------
        sorted_images = sorted(img_metadata, key=lambda x: x["avg"])

        sample = sorted_images[0]
        tile_w, tile_h, batch_capacity = compute_tile_size(
            sample["category"], sample["w"], sample["h"]
        )

        # ---------- CREATE BATCHES ----------
        for i in range(0, len(sorted_images), batch_capacity):

            batch_imgs = sorted_images[i:i+batch_capacity]

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            batch_name = f"Batch-{primary_folder}-{batch_count+1}"

            c.execute("""
                INSERT INTO batches
                (primary_folder, secondary_folder, status,
                 img_w, img_h, expected_count, batch_name, timestamp)
                VALUES (?, ?, 'incomplete', ?, ?, ?, ?, ?)
            """, (primary_folder, secondary_folder,
                  tile_w, tile_h, batch_capacity, batch_name, ts))

            batch_id = c.lastrowid
            batch_count += 1

            for idx, img in enumerate(batch_imgs):
                c.execute("""
                    UPDATE images
                    SET batch_id=?, manual_order=?
                    WHERE file_path=?
                """, (batch_id, idx+1, img["file_path"]))

    conn.commit()

    return {
        "image_count": image_count,
        "batch_count": batch_count,
        "validation_issues": validation_issues
    }


# ---------------- Ensure DB Exists ----------------
init_conn = init_db(DB_PATH)
init_conn.close()


# ---------------- UI ----------------
st.title("Ingestion Scan")

st.write("Database path:")
st.code(str(DB_PATH.resolve()))

if st.button("Start Ingestion Scan"):

    conn = sqlite3.connect(DB_PATH)

    # RESET TABLES EACH RUN
    reset_tables(conn)

    summary = process_images(CLEANED_DIR, conn)

    conn.close()

    st.success("Scan complete")
    st.write("Images processed:", summary["image_count"])
    st.write("Batches created:", summary["batch_count"])

    if summary["validation_issues"]:
        st.warning("Mixed aspect folders:")
        for folder, cats in summary["validation_issues"]:
            st.write(folder, cats)