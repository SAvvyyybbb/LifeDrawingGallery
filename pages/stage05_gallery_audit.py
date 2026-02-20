import streamlit as st
from pathlib import Path
import pandas as pd
from datetime import datetime

# ---------------- Configuration ----------------
import config
IMAGE_DIR = config.GALLERY_UVS_DIR

MASTER_LIST = [
    "SQMG01", "SQMG02", "SQMG03", "SQMG04", "SQMG05",
    "SQMG06", "SQMG07", "SQMG08", "SQMG09", "SQMG10",
    "SQMG11", "SQMG12", "SQMG13", "SQMG14",
    "SQSR01", "SQSR02", "SQSR03", "SQSR04",
    "PTMG01", "PTMG02", "PTMG03", "PTMG04",
    "ETMG01",
    "EWMG01",
]

# ---------------- Helper Logic ----------------
def scan_folder(image_dir: Path):
    if not image_dir.exists():
        return [], False

    files = []
    for p in image_dir.iterdir():
        if p.is_file() and p.suffix.lower() == ".png":
            created = datetime.fromtimestamp(p.stat().st_ctime)
            files.append((p.stem, created))
    return files, True

# ---------------- Streamlit UI ----------------
st.set_page_config(page_title="Gallery UV Audit", layout="centered")
st.title("LifeDrawingGallery – UV Image Audit")
st.caption("Checks presence of required images in `Gallery UVs/` using relative paths.")

found_files, folder_exists = scan_folder(IMAGE_DIR)
found_images = {name: created for name, created in found_files}

if not folder_exists:
    st.error(f"Gallery UVs folder not found: {IMAGE_DIR}")
    st.stop()

# Build results table
rows = []
for name in MASTER_LIST:
    status = "Present" if name in found_images else "Missing"
    created = found_images[name].strftime("%Y-%m-%d %H:%M:%S") if name in found_images else ""
    rows.append({
        "Name": name,
        "Status": status,
        "Created": created
    })

df = pd.DataFrame(rows)

# Unexpected files
unexpected = sorted(set(found_images.keys()) - set(MASTER_LIST))

# ---------------- Display ----------------
st.subheader("Required Images")
st.dataframe(df, use_container_width=True, hide_index=True)

missing_count = (df["Status"] == "Missing").sum()
present_count = (df["Status"] == "Present").sum()

st.markdown(
    f"""
**Summary**
- Present: **{present_count}**
- Missing: **{missing_count}**
"""
)

if unexpected:
    st.subheader("Unexpected Files")
    st.warning("These images exist but are not part of the master list.")
    st.write(unexpected)
else:
    st.subheader("Unexpected Files")
    st.success("No unexpected images found.")