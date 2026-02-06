import streamlit as st
from pathlib import Path
from PIL import Image

THUMBNAIL_SIZE = 100  # width in pixels

def folder_preview_panel(default_folder: Path):
    """
    Display a folder preview with ability to navigate subfolders of main workflow folders.
    """
    # ---------------- Main folders ----------------
    main_folders = {
        "Raw": default_folder.parent / "1_Raw",
        "Cleaned": default_folder,
        "Stitched": default_folder.parent / "3_Stitched",
    }

    # Select main folder
    main_folder_name = st.selectbox("Select Main Folder", options=list(main_folders.keys()))
    main_folder_path = main_folders[main_folder_name]

    if not main_folder_path.exists():
        st.warning(f"Folder does not exist: {main_folder_path}")
        return

    # ---------------- Subfolder selection ----------------
    # List all subfolders recursively including the root itself
    all_subfolders = [main_folder_path] + sorted([p for p in main_folder_path.rglob("*") if p.is_dir()])
    subfolder_options = {str(f.relative_to(main_folder_path)): f for f in all_subfolders}
    
    subfolder_name = st.selectbox("Select Subfolder", options=list(subfolder_options.keys()))
    subfolder_path = subfolder_options[subfolder_name]

    if not subfolder_path.exists():
        st.warning(f"Folder does not exist: {subfolder_path}")
        return

    # ---------------- Gather images ----------------
    img_files = sorted([f for f in subfolder_path.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg")])
    if not img_files:
        st.info("No images found in this folder.")
        return

    # ---------------- Display thumbnails ----------------
    st.write(f"**{subfolder_name} folder ({len(img_files)} images):**")
    cols_per_row = 2  # narrow for right panel
    rows = (len(img_files) + cols_per_row - 1) // cols_per_row

    for r in range(rows):
        cols = st.columns(cols_per_row, gap="small")
        for c in range(cols_per_row):
            idx = r * cols_per_row + c
            if idx >= len(img_files):
                break
            try:
                img = Image.open(img_files[idx])
                img.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE))
                cols[c].image(img, width=THUMBNAIL_SIZE)
            except Exception:
                continue
