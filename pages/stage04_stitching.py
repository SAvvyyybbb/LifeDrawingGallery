# pages/stage04_stitching.py

import streamlit as st
import os
import shutil
from datetime import datetime
from PIL import Image
import pandas as pd
import sqlite3
import imagehash
import hashlib
import config
from pathlib import Path

st.title("Stage 3: UV Map Stitching")

# ---------------- Connect to DB ----------------
if not config.DB_PATH.exists():
    st.error(f"Database not found at {config.DB_PATH}")
    st.stop()

conn = sqlite3.connect(config.DB_PATH)

# ---------------- Required Tables ----------------
conn.execute("""
CREATE TABLE IF NOT EXISTS stitched_phashes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phash TEXT NOT NULL,
    hash TEXT NOT NULL,
    file_path TEXT NOT NULL,
    batch_id INTEGER,
    stitched_date TEXT
)
""")

conn.execute("""
CREATE TABLE IF NOT EXISTS export_moves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id INTEGER,
    src_path TEXT NOT NULL,
    dst_path TEXT NOT NULL,
    export_type TEXT CHECK(export_type IN ('stitched', 'leftover')),
    export_date TEXT
)
""")
conn.commit()

# ---------------- Load Data ----------------
df_batches = pd.read_sql("SELECT * FROM batches ORDER BY id", conn)
df_images = pd.read_sql("SELECT * FROM images ORDER BY batch_id, manual_order", conn)

# ---------------- Source Root ----------------
if not df_images.empty:
    all_paths = [str(Path(p).resolve()) for p in df_images["file_path"]]
    SOURCE_ROOT = Path(os.path.commonpath(all_paths))
else:
    SOURCE_ROOT = config.IMAGE_PROCESSING_DIR.resolve()

# ---------------- Naming & Grid ----------------
ASPECT_CODES = config.ASPECT_CODES
ROOM_CODES = config.ROOM_CODES
DEFAULT_POSITION = config.DEFAULT_POSITION

def grid_for_aspect(aspect):
    return {"Square": (4,4),"Portrait": (4,2),"Extra Tall": (4,2),
            "Landscape": (2,4),"Extra Wide": (2,4)}.get(aspect,(0,0))

def capacity_for_aspect(aspect):
    c,r = grid_for_aspect(aspect)
    return c*r

# ---------------- Auto-update Batch Status ----------------
updated = []
for _, batch in df_batches.iterrows():
    imgs = df_images[df_images["batch_id"] == batch["id"]]
    if imgs.empty:
        continue
    aspects = imgs["aspect_category"].dropna().unique()
    if len(aspects) != 1:
        continue
    if len(imgs) >= capacity_for_aspect(aspects[0]) and batch["status"] != "complete":
        updated.append(batch["id"])
if updated:
    conn.executemany("UPDATE batches SET status = 'complete' WHERE id = ?", [(i,) for i in updated])
    conn.commit()
    df_batches.loc[df_batches["id"].isin(updated), "status"] = "complete"

# ---------------- Session State ----------------
if "selected_batches" not in st.session_state:
    st.session_state.selected_batches = set()

# ---------------- Preview Renderer ----------------
def render_batch_preview(batch_id, batch_imgs):
    canvas = Image.new("RGB", (config.OUTPUT_SIZE, config.OUTPUT_SIZE), (0,0,0))
    x=y=max_h=0
    for _, row in batch_imgs.sort_values("manual_order").iterrows():
        try:
            img = Image.open(row["file_path"]).convert("RGB")
        except Exception:
            continue
        scale = min(1, config.OUTPUT_SIZE/max(img.size))
        img = img.resize((int(img.width*scale), int(img.height*scale)), Image.LANCZOS)
        if x+img.width>config.OUTPUT_SIZE:
            x=0
            y+=max_h
            max_h=0
        if y+img.height>config.OUTPUT_SIZE:
            break
        canvas.paste(img,(x,y))
        x+=img.width
        max_h = max(max_h,img.height)
    return canvas

# ---------------- Helpers ----------------
def compute_phash(path):
    return str(imagehash.phash(Image.open(path)))

def compute_file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def relative_preserve(src_path: str) -> str:
    src_path = Path(src_path).resolve()
    try:
        rel_path = src_path.relative_to(SOURCE_ROOT)
    except ValueError:
        rel_path = src_path.name
    return str(rel_path)

def export_stitched_batches(batch_ids, output_dir=None):
    out_dir = Path(output_dir or config.STITCHED_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    for bid in batch_ids:
        batch = df_batches[df_batches["id"]==bid].iloc[0]
        imgs = df_images[df_images["batch_id"]==bid]
        canvas = render_batch_preview(bid, imgs)

        aspect_code = st.session_state.get(f"batch_aspect_{bid}", "XX")
        room_code   = st.session_state.get(f"batch_room_{bid}", "MG")
        position    = st.session_state.get(f"batch_pos_{bid}", DEFAULT_POSITION)

        uv_name = f"{aspect_code}{room_code}{position}"
        out_path = out_dir / f"{uv_name}.png"
        canvas.save(out_path)

# ---------------- Batch Selector UI ----------------
def batch_selector_ui_grid(df, cols_per_row=3):
    st.subheader("Batches")
    total_batches = len(df)
    rows = (total_batches + cols_per_row - 1) // cols_per_row

    for r in range(rows):
        cols = st.columns(cols_per_row, gap="small")
        for c in range(cols_per_row):
            idx = r * cols_per_row + c
            if idx >= total_batches:
                break
            batch = df.iloc[idx]
            bid = batch["id"]
            imgs = df_images[df_images["batch_id"] == bid]
            if imgs.empty:
                continue

            # Check if any image in this batch is vetoed
            vetoed_imgs = imgs[imgs["veto_ind"]==1]
            if not vetoed_imgs.empty:
                st.warning(f"Batch {batch['batch_name']} contains {len(vetoed_imgs)} vetoed image(s)")

            # Session keys
            key_chk = f"batch_chk_{bid}"
            key_aspect = f"batch_aspect_{bid}"
            key_room = f"batch_room_{bid}"
            key_pos = f"batch_pos_{bid}"

            if key_chk not in st.session_state:
                st.session_state[key_chk] = bid in st.session_state.selected_batches
            if key_aspect not in st.session_state:
                aspect = imgs["aspect_category"].iloc[0] if not imgs.empty else "Square"
                st.session_state[key_aspect] = ASPECT_CODES.get(aspect, "XX")
            if key_room not in st.session_state:
                st.session_state[key_room] = "MG"
            if key_pos not in st.session_state:
                st.session_state[key_pos] = DEFAULT_POSITION

            with cols[c]:
                with st.container():
                    st.write("")
                    checked = st.checkbox(batch["batch_name"], key=key_chk)
                    if checked:
                        st.session_state.selected_batches.add(bid)
                    else:
                        st.session_state.selected_batches.discard(bid)

                    st.image(render_batch_preview(bid, imgs), width=220)
                    st.selectbox("Aspect", options=list(ASPECT_CODES.values()), key=key_aspect)
                    st.selectbox("Room", options=ROOM_CODES, key=key_room)
                    st.text_input("Position", key=key_pos, max_chars=2)
                    st.write("")

# ---------------- Apply UI ----------------
batch_selector_ui_grid(df_batches[df_batches["status"] == "complete"])
batch_selector_ui_grid(df_batches[df_batches["status"] != "complete"])

selected_batches = sorted(st.session_state.selected_batches)

# ---------------- Export + Sort Source Images ----------------
st.divider()

if st.button("Export + Sort Source Images"):
    today = datetime.now().strftime("%Y_%m_%d")
    stitched_root = config.STITCHED_DIR / f"3_Stitched_{today}"
    leftover_root = config.STITCHED_DIR / f"Leftovers_{today}"
    stitched_root.mkdir(parents=True, exist_ok=True)
    leftover_root.mkdir(parents=True, exist_ok=True)

    export_stitched_batches(selected_batches, output_dir=stitched_root)

    stitched_image_ids = set()
    dupes = []

    existing_hashes = pd.read_sql("SELECT phash,hash,batch_id FROM stitched_phashes",conn)

    for bid in selected_batches:
        imgs = df_images[df_images["batch_id"]==bid]
        for _, row in imgs.iterrows():
            src = Path(row["file_path"]).resolve()
            if not src.exists():
                continue
            rel = relative_preserve(src)
            dst = stitched_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

            ph = compute_phash(dst)
            h256 = compute_file_hash(dst)
            stitched_image_ids.add(row["id"])

            match = existing_hashes[existing_hashes["hash"]==h256]
            if not match.empty:
                dupes.append((str(dst), match.iloc[0]["batch_id"]))

            # ---- INSERT into stitched_phashes ----
            conn.execute(
                "INSERT INTO stitched_phashes (phash,hash,file_path,batch_id,stitched_date) VALUES (?,?,?,?,?)",
                (ph,h256,str(dst),bid,today)
            )

            # ---- INSERT into export_moves ----
            conn.execute(
                "INSERT INTO export_moves (image_id,src_path,dst_path,export_type,export_date) VALUES (?,?,?,?,?)",
                (row["id"],str(src),str(dst),'stitched',today)
            )

            # ---- Mark images.is_stitched = 1 ----
            conn.execute(
                "UPDATE images SET is_stitched=1 WHERE hash=?",
                (h256,)
            )

            # ---- Mark raw_image_data.batched = 1 using modified_hash ----
            conn.execute("""
            UPDATE raw_image_data
            SET batched = 1
            WHERE hash IN (
                SELECT COALESCE(r.modified_hash, r.hash)
                FROM raw_image_data r
                JOIN stitched_phashes s ON COALESCE(r.modified_hash, r.hash) = s.hash
                WHERE s.hash = ?
            )
            """, (h256,))

    # ---- Leftovers ----
    leftovers = df_images[~df_images["id"].isin(stitched_image_ids)]
    for _, row in leftovers.iterrows():
        src = Path(row["file_path"]).resolve()
        if not src.exists():
            continue
        rel = relative_preserve(src)
        dst = leftover_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        conn.execute(
            "INSERT INTO export_moves (image_id,src_path,dst_path,export_type,export_date) VALUES (?,?,?,?,?)",
            (row["id"],str(src),str(dst),'leftover',today)
        )

    conn.commit()

    if dupes:
        st.warning("Duplicates detected:")
        for d,b in dupes:
            st.write(f"{d} (matches batch {b})")
    else:
        st.success("Export + Sort completed successfully.")

conn.close()