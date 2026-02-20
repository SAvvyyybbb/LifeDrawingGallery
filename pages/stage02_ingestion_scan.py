from pathlib import Path
from PIL import Image
import imagehash
import numpy as np
import sqlite3
from datetime import datetime
import os
import streamlit as st
import pandas as pd
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

# ---------------- Database Initialization ----------------
def init_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    # batches table
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
    # images table
    c.execute("""
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id INTEGER,
        veto INTEGER,
        file_path TEXT UNIQUE,
        is_stitched INTEGER DEFAULT 0,
        aspect_category TEXT,
        manual_order INTEGER,
        img_w INTEGER,
        img_h INTEGER,
        avg_r REAL,
        avg_g REAL,
        avg_b REAL,
        phash TEXT,
        FOREIGN KEY(batch_id) REFERENCES batches(id)
    )
    """)
    conn.commit()
    return conn

# ---------------- Smart Reconciliation ----------------
def reconcile_db_with_moves(conn: sqlite3.Connection, input_dir: Path):
    """
    - Remove rows for missing files
    - Keep existing files in same folder
    - If moved to a new folder, reset batch_id to assign new batch
    """
    c = conn.cursor()
    
    # Get DB entries
    c.execute("SELECT id, file_path, batch_id FROM images")
    db_rows = c.fetchall()
    
    # Map disk files by file name
    disk_files = [f.resolve() for f in input_dir.rglob("*") if f.suffix.lower() in (".png", ".jpg", ".jpeg")]
    disk_map = {f.name: f for f in disk_files}
    
    existing_files = set()
    
    for row_id, file_path, batch_id in db_rows:
        old_path = Path(file_path)
        fname = old_path.name
        
        if fname in disk_map:
            new_path = disk_map[fname]
            if old_path.parent != new_path.parent:
                # Moved: reset batch_id
                c.execute("UPDATE images SET file_path=?, batch_id=NULL WHERE id=?", (str(new_path), row_id))
            else:
                # Same folder: keep batch_id
                c.execute("UPDATE images SET file_path=? WHERE id=?", (str(new_path), row_id))
            existing_files.add(str(new_path))
        else:
            # Missing: delete from DB
            c.execute("DELETE FROM images WHERE id=?", (row_id,))
    
    conn.commit()
    return existing_files

# ---------------- Image Processing ----------------
def process_images(input_dir: Path, conn: sqlite3.Connection, existing_files=set()):
    c = conn.cursor()
    image_count, batch_count = 0, 0
    validation_issues = []

    for root, _, files in os.walk(input_dir):
        imgs = [f for f in files if f.lower().endswith((".png", ".jpg", ".jpeg"))]
        if not imgs:
            continue

        rel_path = Path(root).relative_to(input_dir)
        parts = rel_path.parts
        primary_folder = parts[0] if len(parts) > 0 else "root"
        secondary_folder = parts[1] if len(parts) > 1 else None

        img_metadata, aspect_set = [], set()

        for f in imgs:
            abs_path = str((Path(root) / f).resolve())
            
            if abs_path in existing_files:
                continue

            try:
                img = Image.open(abs_path).convert("RGB")
                w, h = img.size
                category = compute_aspect_category(w, h)
                arr = np.array(img)
                avg_r, avg_g, avg_b = arr[:, :, 0].mean(), arr[:, :, 1].mean(), arr[:, :, 2].mean()
                p_hash = str(imagehash.phash(img))
                img_metadata.append({
                    "file_path": abs_path,
                    "w": w, "h": h,
                    "category": category,
                    "avg_r": avg_r, "avg_g": avg_g, "avg_b": avg_b,
                    "phash": p_hash
                })
                aspect_set.add(category)
                c.execute("""INSERT INTO images (file_path, aspect_category, img_w, img_h, avg_r, avg_g, avg_b, phash)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                          (abs_path, category, w, h, avg_r, avg_g, avg_b, p_hash))
                image_count += 1
            except Exception as e:
                print(f"Skipping {abs_path}: {e}")
                continue

        if len(aspect_set) > 1:
            validation_issues.append((str(rel_path), list(aspect_set)))
        if not img_metadata:
            continue

        # Sort by brightness
        avg_colors = np.array([(d['avg_r']+d['avg_g']+d['avg_b'])/3 for d in img_metadata])
        sorted_indices = np.argsort(avg_colors)
        sorted_images = [img_metadata[i] for i in sorted_indices]

        sample_data = sorted_images[0]
        tile_w, tile_h, batch_capacity = compute_tile_size(sample_data['category'], sample_data['w'], sample_data['h'])

        for i in range(0, len(sorted_images), batch_capacity):
            batch_imgs = sorted_images[i:i+batch_capacity]
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            batch_name = f"Batch-{primary_folder}-{batch_count+1}"
            c.execute("""INSERT INTO batches (primary_folder, secondary_folder, status, img_w, img_h, expected_count, batch_name, timestamp)
                         VALUES (?, ?, 'incomplete', ?, ?, ?, ?, ?)""",
                      (primary_folder, secondary_folder, tile_w, tile_h, batch_capacity, batch_name, ts))
            batch_id = c.lastrowid
            batch_count += 1

            for idx, img in enumerate(batch_imgs):
                c.execute("UPDATE images SET batch_id=?, manual_order=? WHERE file_path=?", (batch_id, idx+1, img['file_path']))

    conn.commit()
    return {"image_count": image_count, "batch_count": batch_count, "validation_issues": validation_issues}


# ---------------- Streamlit UI ----------------
st.title("Stage 1: Ingestion Scan")
st.write("Scans cleaned images and creates batches for layout & UV stitching.")

if st.button("Start Ingestion Scan"):
    conn = init_db(DB_PATH)

    # Smart reconciliation
    existing_files = reconcile_db_with_moves(conn, CLEANED_DIR)

    # Process new / moved images
    summary = process_images(CLEANED_DIR, conn, existing_files)
    conn.close()

    st.success("Ingestion scan complete!")
    st.write(f"Total new images processed: {summary['image_count']}")
    st.write(f"Total batches created: {summary['batch_count']}")
    if summary["validation_issues"]:
        st.warning("Some folders contained mixed aspect ratios:")
        for folder, categories in summary["validation_issues"]:
            st.write(f" - {folder}: {categories}")


# ---------------- Database Audit Panel ----------------
with st.expander("📊 Audit Current Image Database", expanded=False):
    conn = sqlite3.connect(DB_PATH)
    images_df = pd.read_sql_query("SELECT * FROM images", conn)
    batches_df = pd.read_sql_query("SELECT * FROM batches", conn)

    st.write(f"Total images in DB: {len(images_df)}")
    st.write(f"Total batches in DB: {len(batches_df)}")

    # Clear cache button
    if st.button("🗑️ Clear Current Cache"):
        c = conn.cursor()
        c.execute("DELETE FROM images")
        c.execute("DELETE FROM batches")
        conn.commit()
        st.warning("Database cache cleared!")
        images_df = pd.DataFrame()
        batches_df = pd.DataFrame()

    # Filter by batch
    batch_options = ["All"] + batches_df["batch_name"].tolist() if not batches_df.empty else ["All"]
    selected_batch = st.selectbox("Filter by batch", options=batch_options)

    if selected_batch != "All" and not batches_df.empty:
        batch_id = batches_df.loc[batches_df["batch_name"] == selected_batch, "id"].values[0]
        images_df = images_df[images_df["batch_id"] == batch_id]

    if not images_df.empty:
        display_df = images_df[[
            "file_path", "aspect_category", "img_w", "img_h",
            "avg_r", "avg_g", "avg_b", "batch_id", "manual_order"
        ]].copy()
        display_df.rename(columns={
            "file_path": "File",
            "aspect_category": "Aspect",
            "img_w": "Width",
            "img_h": "Height",
            "avg_r": "Avg R",
            "avg_g": "Avg G",
            "avg_b": "Avg B",
            "batch_id": "Batch ID",
            "manual_order": "Order"
        }, inplace=True)

        st.dataframe(display_df, height=400)
    else:
        st.info("No images to display.")

    conn.close()
