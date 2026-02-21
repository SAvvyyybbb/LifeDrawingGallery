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
st.write("""
Preview the layout for the UV map that will be uploaded to the gallery. Move images between batches or reorder them.

The dropdowns below follow the folder structure you have set up in the previous step.
""")

# ---------------- Verify DB ----------------
if not DB_PATH.exists():
    st.warning(f"Database file does not exist: {DB_PATH}")
    st.stop()

conn = sqlite3.connect(DB_PATH)

# ---------------- Helpers ----------------
def load_batches():
    df = pd.read_sql("SELECT * FROM batches ORDER BY id", conn)
    if not df.empty:
        df.columns = [
            'id', 'primary_folder', 'aspect_ratio', 'secondary_folder', 'batch_name',
            'width', 'height', 'batch_number', 'timestamp'
        ]
        df['primary_folder'] = df['primary_folder'].astype(str).str.strip()
        df['aspect_ratio'] = df['aspect_ratio'].astype(str).str.strip()
    return df


def load_images(batch_id):
    return pd.read_sql(
        "SELECT * FROM images WHERE batch_id=? ORDER BY manual_order",
        conn, params=(batch_id,)
    )


# ---------- ORDER SWAP LOGIC ----------
def move_image(batch_id, img_id, direction):
    cur = conn.cursor()

    cur.execute(
        "SELECT id, manual_order FROM images WHERE id=? AND batch_id=?",
        (img_id, batch_id)
    )
    row = cur.fetchone()
    if not row:
        return

    current_order = row[1]

    if direction == "up":
        cur.execute(
            """
            SELECT id, manual_order FROM images
            WHERE batch_id=? AND manual_order < ?
            ORDER BY manual_order DESC LIMIT 1
            """,
            (batch_id, current_order)
        )
    else:
        cur.execute(
            """
            SELECT id, manual_order FROM images
            WHERE batch_id=? AND manual_order > ?
            ORDER BY manual_order ASC LIMIT 1
            """,
            (batch_id, current_order)
        )

    swap = cur.fetchone()
    if not swap:
        return

    swap_id, swap_order = swap

    # swap values
    cur.execute("UPDATE images SET manual_order=? WHERE id=?", (swap_order, img_id))
    cur.execute("UPDATE images SET manual_order=? WHERE id=?", (current_order, swap_id))
    conn.commit()


# ---------- PREVIEW RENDER ----------
def render_batch_preview(df_ordered, scale=0.25):
    if df_ordered.empty:
        st.write("No images to preview.")
        return

    aspect = df_ordered["aspect_category"].iloc[0]
    num_images = len(df_ordered)

    # grid logic
    if aspect == "Square":
        cols = min(4, num_images)
    elif aspect in ["Extra Tall", "Portrait"]:
        cols = min(4, num_images)
    elif aspect in ["Extra Wide", "Landscape"]:
        cols = min(2, num_images)
    else:
        cols = min(4, num_images)

    rows = math.ceil(num_images / cols)

    tile_w = int(OUTPUT_SIZE / max(cols, 1) * scale)
    tile_h = int(OUTPUT_SIZE / max(rows, 1) * scale)
    preview_img = Image.new("RGB", (cols * tile_w, rows * tile_h), (30, 30, 30))

    try:
        font = ImageFont.truetype("arial.ttf", max(12, int(12*scale)))
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
                tile = Image.new("RGB", (tile_w, tile_h), (50,50,50))
                tile.paste(img_resized, ((tile_w - new_w)//2, (tile_h - new_h)//2))

                draw = ImageDraw.Draw(tile)
                order_display = row["manual_order"] if row["manual_order"] is not None else "-"
                draw.text((5,5), str(order_display), fill=(255,255,255), font=font)

                preview_img.paste(tile, (c*tile_w, r*tile_h))

            except Exception as e:
                st.warning(f"Failed to load {row['file_path']}: {e}")

            idx += 1

    scaled_width = int(OUTPUT_SIZE * scale)
    st.image(
        preview_img,
        caption=f"Batch {df_ordered['batch_id'].iloc[0]} Layout ({aspect})",
        width=scaled_width
    )


# ---------------- Main Workflow ----------------
df_batches = load_batches()

if df_batches.empty:
    st.info("No batches found in the database. Create some batches first to preview images.")
    conn.close()

else:

    # ---------- Batch Selection ----------
    primary_options = sorted(df_batches['primary_folder'].dropna().unique())
    if not primary_options:
        st.info("No primary folders available in batches.")
        conn.close()
        st.stop()

    selected_primary = st.selectbox("Select Primary Folder", primary_options)
    df_primary = df_batches[df_batches['primary_folder'] == selected_primary]

    secondary_options = sorted(df_primary['aspect_ratio'].dropna().unique())
    if secondary_options:
        selected_secondary = st.selectbox("Select Secondary Folder", secondary_options)
        df_secondary = df_primary[df_primary['aspect_ratio'] == selected_secondary]
    else:
        df_secondary = df_primary

    batch_map = dict(zip(df_secondary['id'], df_secondary['batch_name']))

    selected_batch_id = st.selectbox(
        "Select Batch Number",
        options=df_secondary['id'],
        format_func=lambda x: f"{x} - {batch_map[x]}"
    )

    # ---------- Load Images ----------
    df_images = load_images(selected_batch_id)

    if df_images.empty:
        st.info("No images found for this batch yet. Upload or generate images first.")

    else:
        st.subheader("Manual Ordering")

        ordered = df_images.sort_values("manual_order").reset_index(drop=True)

        for i, row in ordered.iterrows():
            col1, col2, col3 = st.columns([6,1,1])

            with col1:
                st.write(f"{row['manual_order']} — {Path(row['file_path']).name}")

            with col2:
                if st.button("↑", key=f"up_{row['id']}"):
                    move_image(selected_batch_id, row["id"], "up")
                    st.rerun()

            with col3:
                if st.button("↓", key=f"down_{row['id']}"):
                    move_image(selected_batch_id, row["id"], "down")
                    st.rerun()

        st.subheader("Batch Preview")
        render_batch_preview(ordered)

    conn.close()