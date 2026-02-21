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
    "Preview layout for UV map upload. Reorder images or move them between batches."
)

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

    # grid logic
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
        "UPDATE images SET manual_order=? WHERE id=?",
        (int(value), int(img_id)),
    )
    conn.commit()


def shift_order(img_id, direction):
    cur = conn.execute(
        "SELECT manual_order, batch_id FROM images WHERE id=?",
        (img_id,),
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
            "UPDATE images SET manual_order=? WHERE id=?",
            (swap["manual_order"], img_id),
        )
        conn.execute(
            "UPDATE images SET manual_order=? WHERE id=?",
            (current_order, swap["id"]),
        )
        conn.commit()


# ---------------- Main Workflow ----------------
df_batches = load_batches()

if df_batches.empty:
    st.info("No batches found. Create batches first.")
    conn.close()
    st.stop()

# ---------- selectors ----------
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

# ---------- load images ----------
df_images = load_images(selected_batch_id)

if df_images.empty:
    st.info("No images in this batch.")
    conn.close()
    st.stop()

# ---------- preview ----------
st.subheader("Batch Preview")
render_batch_preview(df_images.sort_values("manual_order").reset_index(drop=True))

st.divider()

# ---------- compact editor ----------
st.subheader("Reorder Images")

cols_per_row = 6
rows = math.ceil(len(df_images) / cols_per_row)

idx = 0
for r in range(rows):
    cols = st.columns(cols_per_row)

    for c in range(cols_per_row):
        if idx >= len(df_images):
            break

        row = df_images.iloc[idx]

        with cols[c]:
            img_name = Path(row["file_path"]).name
            img_path = CLEANED_DIR / row["aspect_category"] / img_name

            try:
                st.image(img_path, use_container_width=True)
            except:
                st.empty()

            new_val = st.number_input(
                "Order",
                value=int(row["manual_order"]),
                step=1,
                key=f"order_{row['id']}",
                label_visibility="collapsed",
            )

            if new_val != row["manual_order"]:
                update_order(row["id"], new_val)
                st.rerun()

            b1, b2 = st.columns(2)
            if b1.button("↑", key=f"up_{row['id']}"):
                shift_order(row["id"], -1)
                st.rerun()

            if b2.button("↓", key=f"down_{row['id']}"):
                shift_order(row["id"], 1)
                st.rerun()

        idx += 1

conn.close()