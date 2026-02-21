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

st.title("Batch Layout & Ordering")

# ---------------- Verify DB ----------------
if not DB_PATH.exists():
    st.warning(f"Database file does not exist: {DB_PATH}")
    st.stop()

conn = sqlite3.connect(DB_PATH)

# ---------------- Session State ----------------
if "last_changed" not in st.session_state:
    st.session_state.last_changed = None


# ---------------- Helpers ----------------
def load_batches():
    df = pd.read_sql("SELECT * FROM batches ORDER BY id", conn)
    if not df.empty:
        df.columns = [
            'id','primary_folder','aspect_ratio','secondary_folder',
            'batch_name','width','height','batch_number','timestamp'
        ]
    return df


def load_images(batch_id):
    return pd.read_sql(
        "SELECT * FROM images WHERE batch_id=? ORDER BY manual_order",
        conn, params=(batch_id,)
    )


# ---------- ORDER UPDATE ----------
def set_order(batch_id, img_id, new_order):

    cur = conn.cursor()

    # clamp value
    cur.execute("SELECT COUNT(*) FROM images WHERE batch_id=?", (batch_id,))
    max_order = cur.fetchone()[0]

    new_order = max(1, min(new_order, max_order))

    # current order
    cur.execute(
        "SELECT manual_order FROM images WHERE id=? AND batch_id=?",
        (img_id, batch_id)
    )
    old_order = cur.fetchone()[0]

    if new_order == old_order:
        return

    # shift other rows
    if new_order < old_order:
        cur.execute("""
            UPDATE images
            SET manual_order = manual_order + 1
            WHERE batch_id=? AND manual_order >= ? AND manual_order < ?
        """, (batch_id, new_order, old_order))
    else:
        cur.execute("""
            UPDATE images
            SET manual_order = manual_order - 1
            WHERE batch_id=? AND manual_order <= ? AND manual_order > ?
        """, (batch_id, new_order, old_order))

    # set new position
    cur.execute(
        "UPDATE images SET manual_order=? WHERE id=?",
        (new_order, img_id)
    )

    conn.commit()
    st.session_state.last_changed = img_id


# ---------- PREVIEW ----------
def render_batch_preview(df_ordered, scale=0.25):

    if df_ordered.empty:
        st.write("No images.")
        return

    aspect = df_ordered["aspect_category"].iloc[0]
    num_images = len(df_ordered)

    cols = 2 if aspect in ["Extra Wide","Landscape"] else 4
    cols = min(cols, num_images)
    rows = math.ceil(num_images / cols)

    tile_w = int(OUTPUT_SIZE / cols * scale)
    tile_h = int(OUTPUT_SIZE / rows * scale)

    canvas = Image.new("RGB", (cols*tile_w, rows*tile_h), (30,30,30))

    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except:
        font = ImageFont.load_default()

    i = 0
    for r in range(rows):
        for c in range(cols):
            if i >= num_images:
                break

            row = df_ordered.iloc[i]
            try:
                path = CLEANED_DIR / row["aspect_category"] / Path(row["file_path"]).name
                img = Image.open(path).convert("RGB")

                ratio = img.width/img.height
                target = tile_w/tile_h

                if ratio > target:
                    nw = tile_w
                    nh = int(tile_w/ratio)
                else:
                    nh = tile_h
                    nw = int(tile_h*ratio)

                img = img.resize((nw,nh), Image.LANCZOS)

                tile = Image.new("RGB",(tile_w,tile_h),(50,50,50))
                tile.paste(img,((tile_w-nw)//2,(tile_h-nh)//2))

                draw = ImageDraw.Draw(tile)
                draw.text((6,6), str(row["manual_order"]), fill=(255,255,255), font=font)

                canvas.paste(tile,(c*tile_w,r*tile_h))
            except:
                pass

            i+=1

    st.image(canvas,width=int(OUTPUT_SIZE*scale))


# ---------------- Main ----------------
df_batches = load_batches()

if df_batches.empty:
    st.info("No batches found.")
    st.stop()

primary = st.selectbox("Primary", sorted(df_batches.primary_folder.unique()))
df_primary = df_batches[df_batches.primary_folder==primary]

aspect = st.selectbox("Aspect", sorted(df_primary.aspect_ratio.unique()))
df_secondary = df_primary[df_primary.aspect_ratio==aspect]

batch_map = dict(zip(df_secondary.id, df_secondary.batch_name))

batch_id = st.selectbox(
    "Batch",
    options=df_secondary.id,
    format_func=lambda x: f"{x} - {batch_map[x]}"
)

df_images = load_images(batch_id)

if df_images.empty:
    st.info("No images.")
    st.stop()

ordered = df_images.sort_values("manual_order").reset_index(drop=True)

# ---------- PREVIEW ----------
st.subheader("Preview")
render_batch_preview(ordered)


# ---------- INLINE ORDER EDITOR ----------
st.subheader("Reorder")

cols_per_row = 8
rows = math.ceil(len(ordered)/cols_per_row)

st.markdown("""
<style>
.flash {
    animation: flash 0.6s ease;
}
@keyframes flash {
    0% {background:#4CAF50;}
    100% {background:transparent;}
}
</style>
""", unsafe_allow_html=True)

idx=0
for r in range(rows):
    cols = st.columns(cols_per_row)

    for c in cols:
        if idx>=len(ordered):
            break

        row = ordered.iloc[idx]
        highlight = "flash" if st.session_state.last_changed==row["id"] else ""

        with c:
            st.markdown(f"<div class='{highlight}'>",unsafe_allow_html=True)

            val = st.number_input(
                label="",
                min_value=1,
                max_value=len(ordered),
                value=int(row["manual_order"]),
                key=f"order_{row['id']}",
                step=1
            )

            if val != row["manual_order"]:
                set_order(batch_id,row["id"],val)
                st.rerun()

            st.markdown("</div>",unsafe_allow_html=True)

        idx+=1

conn.close()