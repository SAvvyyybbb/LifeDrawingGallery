# gallery_uv_audit.py
import streamlit as st
import pandas as pd
import config  # <-- your existing config.py
from pathlib import Path

# ---------------- Master List of Expected Images ----------------
MASTER_LIST = [
    "SQMG01", "SQMG02", "SQMG03", "SQMG04", "SQMG05",
    "SQMG06", "SQMG07", "SQMG08", "SQMG09", "SQMG10",
    "SQMG11", "SQMG12", "SQMG13", "SQMG14",
    "SQSR01", "SQSR02", "SQSR03", "SQSR04",
    "PTMG01", "PTMG02", "PTMG03", "PTMG04",
    "ETMG01",
    "EWMG01",
]

# ---------------- Image Directory ----------------
IMAGE_DIR = config.GALLERY_UVS_DIR

# ---------------- Helper Logic ----------------
def scan_folder(image_dir: Path):
    """
    Returns set of image stems found in folder, plus a flag if folder exists.
    """
    if not image_dir.exists():
        return set(), False
    found = {p.stem for p in image_dir.iterdir() if p.is_file() and p.suffix.lower() == ".png"}
    return found, True

# ---------------- Streamlit UI ----------------
st.set_page_config(page_title="Gallery UV Audit", layout="centered")
st.title("LifeDrawingGallery – UV Image Audit")
st.caption(f"Checks presence of required images in `{IMAGE_DIR.relative_to(config.ROOT_DIR)}` using project-relative paths.")

found_images, folder_exists = scan_folder(IMAGE_DIR)
if not folder_exists:
    st.error(f"Gallery UVs folder not found at `{IMAGE_DIR}`")
    st.stop()

# ---------------- Build Results Table ----------------
rows = [{"Name": name, "Status": "Present" if name in found_images else "Missing"} for name in MASTER_LIST]
df = pd.DataFrame(rows)

# Unexpected files
unexpected = sorted(found_images - set(MASTER_LIST))

# ---------------- Display Results ----------------
st.subheader("Required Images")
st.dataframe(df, use_container_width=True, hide_index=True)

missing_count = (df["Status"] == "Missing").sum()
present_count = (df["Status"] == "Present").sum()
st.markdown(
    f"**Summary**\n- Present: **{present_count}**\n- Missing: **{missing_count}**"
)

st.subheader("Unexpected Files")
if unexpected:
    st.warning("These images exist but are not part of the master list.")
    st.write(unexpected)
else:
    st.success("No unexpected images found.")