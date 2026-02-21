import streamlit as st
import sqlite3
import math
from PIL import Image, ImageDraw, ImageFont
import pandas as pd
from pathlib import Path
import config

# ---------------- Config ----------------
CLEANED_DIR = config.CLEANED_DIR
DB_PATH = config.DB_PATH
OUTPUT_SIZE = config.OUTPUT_SIZE

st.title("Batch Layout & Manual Ordering")
st.write(
    "Preview layout for UV map upload. Reorder images or reassign them to a different batch (same aspect category)."
)

# ---------------- Session-state rerun helper ----------------
if "rerun_flag" not in st.session_state:
    st.session_state["rerun_flag"] = False


def trigger_rerun():
    st.session_state["rerun_flag"] = not st.session_state["rerun_flag"]
    st.stop()


# ---------------- Verify DB ----------------
if not DB_PATH.exists():
    st.warning(f"Database file does not exist: {DB_PATH}")
    st.stop()

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row

# ---------------- Helpers ----------------
def load_batches():
    df = pd.read_sql("SELECT * FROM batches ORDER BY id", conn)
    if not df.empty:
        df.columns = [
            "id",
            "primary_folder",
            "aspect_ratio",
            "secondary_folder",
            "batch_name",
            "width",
            "height",
            "batch_number",
            "timestamp",
        ]
        df["primary_folder"] = df["primary_folder"].astype(str).str.strip()
        df["aspect_ratio"] = df["aspect_ratio"].astype(str).str.strip()
    return df


def load_images(batch_id):
    return pd.read_sql(
        "SELECT * FROM images WHERE batch_id=? ORDER BY manual_order",
        conn,
        params=(batch_id,),
    )


def render_batch_preview(df_ordered, scale=0.25):
    if df_ordered.empty:
        st.write("No images to preview.")
        return

    aspect = df_ordered["aspect_category"].iloc[0]
    num_images = len(df_ordered)

    if aspect in ["Extra Wide", "Landscape"]:
        cols = min(2, num_images)
    else:
        cols = min(4, num_images)

    rows = math.ceil(num_images / cols)

    tile_w = int(OUTPUT_SIZE / max(cols, 1) * scale)
    tile_h = int(OUTPUT_SIZE / max(rows, 1) * scale)
    preview_img = Image.new("RGB", (cols * tile_w, rows * tile_h), (30, 30, 30))

    try:
        font = ImageFont.truetype("arial.ttf", max(12, int(12 * scale)))
    except:
        font = ImageFont.load_default()

    idx = 0
    for r in range(rows):
        for c in range(cols):
            if idx >= num_images:
                break

            row = df_ordered.iloc[idx]

            try:
                img_name = Path(row["file_path"]).name
                img_path = CLEANED_DIR / row["aspect_category"] / img_name
                img = Image.open(img_path).convert("RGB")

                img_ratio = img.width / img.height
                tile_ratio = tile_w / tile_h

                if img_ratio > tile_ratio:
                    new_w = tile_w
                    new_h = int(tile_w / img_ratio)
                else:
                    new_h = tile_h
                    new_w = int(tile_h * img_ratio)

                img_resized = img.resize((new_w, new_h), Image.LANCZOS)
                tile = Image.new("RGB", (tile_w, tile_h), (50, 50, 50))
                tile.paste(img_resized, ((tile_w - new_w) // 2, (tile_h - new_h) // 2))

                draw = ImageDraw.Draw(tile)
                order_display = (
                    row["manual_order"] if row["manual_order"] is not None else "-"
                )
                draw.text((5, 5), str(order_display), fill=(255, 255, 255), font=font)

                preview_img.paste(tile, (c * tile_w, r * tile_h))

            except Exception as e:
                st.warning(f"Failed to load image: {e}")

            idx += 1

    st.image(
        preview_img,
        caption=f"Batch {df_ordered['batch_id'].iloc[0]} Layout ({aspect})",
        width=int(OUTPUT_SIZE * scale),
    )


def update_order(img_id, value):
    conn.execute(
        "UPDATE images SET manual_order=? WHERE id=?", (int(value), int(img_id))
    )
    conn.commit()


def shift_order(img_id, direction):
    cur = conn.execute(
        "SELECT manual_order, batch_id FROM images WHERE id=?", (img_id,)
    ).fetchone()
    if not cur:
        return

    current_order = cur["manual_order"]
    batch_id = cur["batch_id"]

    swap = conn.execute(
        "SELECT id, manual_order FROM images WHERE batch_id=? AND manual_order=?",
        (batch_id, current_order + direction),
    ).fetchone()

    if swap:
        conn.execute(
            "UPDATE images SET manual_order=? WHERE id=?", (swap["manual_order"], img_id)
        )
        conn.execute(
            "UPDATE images SET manual_order=? WHERE id=?", (current_order, swap["id"])
        )
        conn.commit()


def reassign_batch(img_id, new_batch_id):
    max_order = conn.execute(
        "SELECT MAX(manual_order) as max_order FROM images WHERE batch_id=?",
        (new_batch_id,),
    ).fetchone()["max_order"]
    new_order = 1 if max_order is None else max_order + 1

    conn.execute(
        "UPDATE images SET batch_id=?, manual_order=? WHERE id=?",
        (new_batch_id, new_order, img_id),
    )
    conn.commit()


# ---------------- Main Workflow ----------------
df_batches = load_batches()
if df_batches.empty:
    st.info("No batches found. Create batches first.")
    conn.close()
    st.stop()

primary_options = sorted(df_batches["primary_folder"].dropna().unique())
selected_primary = st.selectbox("Primary Folder", primary_options)
df_primary = df_batches[df_batches["primary_folder"] == selected_primary]

secondary_options = sorted(df_primary["aspect_ratio"].dropna().unique())
selected_secondary = st.selectbox("Aspect Folder", secondary_options)
df_secondary = df_primary[df_primary["aspect_ratio"] == selected_secondary]

batch_map = dict(zip(df_secondary["id"], df_secondary["batch_name"]))

selected_batch_id = st.selectbox(
    "Batch",
    options=df_secondary["id"],
    format_func=lambda x: f"{x} — {batch_map[x]}",
)

df_images = load_images(selected_batch_id)
if df_images.empty:
    st.info("No images in this batch.")
    conn.close()
    st.stop()

# ---------- preview ----------
st.subheader("Batch Preview")
render_batch_preview(df_images.sort_values("manual_order").reset_index(drop=True))
st.divider()

# ---------- editor ----------
st.subheader("Reorder / Reassign Images")
cols_per_row = 3  # number of images per row

aspect_category = df_images.iloc[0]["aspect_category"]
allowed_batches = df_secondary[df_secondary["aspect_ratio"] == aspect_category]
batch_options = {row["id"]: row["batch_name"] for _, row in allowed_batches.iterrows()}

# loop over images in chunks of cols_per_row
for i in range(0, len(df_images), cols_per_row):
    row_images = df_images.iloc[i:i + cols_per_row]
    cols = st.columns(len(row_images))
    for col, (_, row) in zip(cols, row_images.iterrows()):
        with col:
            with st.container():  # each image + widgets in its own container
                img_path = CLEANED_DIR / row["aspect_category"] / Path(row["file_path"]).name
                try:
                    st.image(img_path, use_container_width=True)
                except:
                    st.empty()

                # numeric order input
                new_val = st.number_input(
                    "Order",
                    value=int(row["manual_order"]),
                    step=1,
                    key=f"order_{row['id']}",
                    label_visibility="collapsed",
                )
                if new_val != row["manual_order"]:
                    update_order(row["id"], new_val)
                    trigger_rerun()

                # batch reassignment dropdown
                allowed_keys = list(batch_options.keys())
                selected_index = allowed_keys.index(row["batch_id"]) if row["batch_id"] in allowed_keys else 0
                new_batch = st.selectbox(
                    "Batch",
                    options=allowed_keys,
                    format_func=lambda x: batch_options[x],
                    index=selected_index,
                    key=f"batch_{row['id']}_batch",
                    label_visibility="collapsed",
                )
                if new_batch != row["batch_id"]:
                    reassign_batch(row["id"], new_batch)
                    trigger_rerun()

                # up / down buttons
                b1, b2 = st.columns(2)
                if b1.button("↑", key=f"up_{row['id']}"):
                    shift_order(row["id"], -1)
                    trigger_rerun()
                if b2.button("↓", key=f"down_{row['id']}"):
                    shift_order(row["id"], 1)
                    trigger_rerun()

conn.close()
