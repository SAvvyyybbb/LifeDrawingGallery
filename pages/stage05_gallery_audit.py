import streamlit as st
from pathlib import Path
import pandas as pd

# ---------------- Configuration ----------------

ROOT_DIR = Path(__file__).parent
IMAGE_DIR = ROOT_DIR / "Gallery UVs"

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
        return set(), False

    found = {
        p.stem
        for p in image_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".png"
    }
    return found, True


# ---------------- Streamlit UI ----------------

st.set_page_config(page_title="Gallery UV Audit", layout="centered")

st.title("LifeDrawingGallery – UV Image Audit")

st.caption("Checks presence of required images in `Gallery UVs/` using relative paths.")

found_images, folder_exists = scan_folder(IMAGE_DIR)

if not folder_exists:
    st.error("Gallery UVs folder not found relative to this script.")
    st.stop()

# Build results table
rows = []
for name in MASTER_LIST:
    rows.append({
        "Name": name,
        "Status": "Present" if name in found_images else "Missing"
    })

df = pd.DataFrame(rows)

# Unexpected files
unexpected = sorted(found_images - set(MASTER_LIST))

# ---------------- Display ----------------

st.subheader("Required Images")

st.dataframe(
    df,
    use_container_width=True,
    hide_index=True,
)

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

