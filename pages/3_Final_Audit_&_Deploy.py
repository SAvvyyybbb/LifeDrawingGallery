import streamlit as st
import pandas as pd
from PIL import Image
import config
from pathlib import Path
import io
import shutil
import git_helper
from datetime import datetime

st.set_page_config(page_title="Final Audit & Deploy", layout="wide")

st.title("🚀 Final Audit & Deploy")
st.markdown("Validate all required UV maps against the master list and deploy to GitHub.")

# ---------------- Load Master List ----------------
try:
    master_df = pd.read_csv("MASTER_LIST.csv")
    MASTER_FILES = master_df["Name"].tolist()
except Exception as e:
    st.error(f"Error loading MASTER_LIST.csv: {e}")
    st.stop()

# ---------------- Database Connection ----------------
try:
    conn = config.get_db_connection()
    cursor = conn.cursor(cursor_factory=config.psycopg2.extras.RealDictCursor)
except Exception as e:
    st.error(f"Failed to connect to cloud database: {e}")
    st.stop()

# ---------------- Session State ----------------
if "validated_files" not in st.session_state:
    st.session_state.validated_files = set()

# ---------------- Helpers ----------------
def validate_image(image_bytes, name):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()
        img = Image.open(io.BytesIO(image_bytes))
        if img.size == (2048, 2048):
            return True, "Valid (2048x2048)"
        else:
            return False, f"Invalid Size: {img.size}"
    except Exception as e:
        return False, f"Corrupt or Invalid: {e}"

@st.cache_data(show_spinner=False)
def get_uv_preview(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.thumbnail((400, 400))
        return img
    except:
        return None

def get_local_uv_preview(filename):
    path = Path("Gallery UVs") / filename
    if path.exists():
        try:
            img = Image.open(path)
            img.thumbnail((400, 400))
            return img
        except:
            return None
    return None

# ---------------- Data Loading ----------------
with st.spinner("Checking cloud storage..."):
    try:
        cloud_files = config.supabase_storage_client.storage.from_("uv_maps").list()
        cloud_filenames = [f['name'] for f in cloud_files if f['name'].endswith(".png")]
    except Exception as e:
        st.error(f"Error listing cloud files: {e}")
        st.stop()

# ---------------- Sidebar / Safety Toggle ----------------
with st.sidebar:
    st.title("🔒 Safety Controls")
    dry_run = st.toggle("Dry Run Mode (Prevents GitHub Push)", value=True, help="Disable this to allow actual deployment to GitHub.")
    
    st.divider()
    st.subheader("Utilities")
    if st.button("Clear Preview Caches"):
        st.cache_data.clear()
        st.success("Caches cleared!")
        st.rerun()

# ---------------- Audit & Comparison ----------------
st.subheader("Master List Audit & Comparison")
st.write("Compare the newly stitched UV maps (Cloud) with the current production versions (Local/GitHub).")

for filename in MASTER_FILES:
    status = "Present" if filename in cloud_filenames else "Missing"
    
    with st.expander(f"{filename} - {status}", expanded=(status == "Present")):
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**New (Cloud)**")
            if status == "Present":
                try:
                    image_data = config.supabase_storage_client.storage.from_("uv_maps").download(filename)
                    cloud_prev = get_uv_preview(image_data)
                    if cloud_prev:
                        st.image(cloud_prev, width="stretch")
                    else:
                        st.error("Failed to render cloud preview")
                except:
                    st.error("Download failed")
            else:
                st.info("No new version prepared.")
        
        with col2:
            st.write("**Current (Repository)**")
            local_prev = get_local_uv_preview(filename)
            if local_prev:
                st.image(local_prev, width="stretch")
            else:
                st.info("No existing version found in repository.")
        
        # Audit Toggle
        validated = filename in st.session_state.validated_files
        if st.checkbox("Ready to Replace/Keep", key=f"audit_{filename}", value=validated):
            st.session_state.validated_files.add(filename)
        elif validated:
            st.session_state.validated_files.remove(filename)

# ---------------- Deployment ----------------
st.divider()
st.subheader("Archive & Deploy to GitHub")

# Logic: Deployment is allowed if all files in MASTER_FILES are audited.
all_audited = all(f in st.session_state.validated_files for f in MASTER_FILES)

if not all_audited:
    st.warning(f"Cannot deploy: {len(MASTER_FILES) - len(st.session_state.validated_files)} files still need to be audited.")
else:
    if dry_run:
        st.info("ℹ️ **Dry Run Active:** The deploy button will perform a mock run (logging only). Disable 'Dry Run Mode' in the sidebar to push for real.")
    else:
        st.success("🎉 All files audited! Ready for archiving and GitHub deployment.")
    
    if st.button("🚀 Archive Locals & Push to GitHub", type="primary"):
        to_replace = [f for f in st.session_state.validated_files if f in cloud_filenames]
        
        if dry_run:
            st.code(f"MOCK RUN: Would archive {len(to_replace)} local files and replace them in 'Gallery UVs', then push to Git:\n" + "\n".join(to_replace))
        else:
            with st.spinner(f"Archiving old versions and downloading {len(to_replace)} new UV maps..."):
                try:
                    uv_dir = Path("Gallery UVs")
                    uv_dir.mkdir(exist_ok=True)
                    
                    archive_dir = uv_dir / "Archive"
                    archive_dir.mkdir(exist_ok=True)
                    
                    for filename in to_replace:
                        local_path = uv_dir / filename
                        
                        # 1. Archive the existing file if it exists
                        if local_path.exists():
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            archive_path = archive_dir / f"{local_path.stem}_{timestamp}{local_path.suffix}"
                            shutil.copy2(local_path, archive_path)
                            
                        # 2. Download new version from Supabase
                        image_data = config.supabase_storage_client.storage.from_("uv_maps").download(filename)
                        local_path.write_bytes(image_data)
                    
                    st.success("Files downloaded and archived successfully.")
                    
                except Exception as e:
                    st.error(f"Download or Archive failed: {e}")
                    st.stop()
                    
            with st.spinner("Pushing changes to GitHub..."):
                try:
                    repo_root = config.ROOT_DIR
                    git_helper.git_pull(repo_root)
                    git_helper.git_add(repo_root)
                    
                    # Commit and push
                    committed = git_helper.git_commit(repo_root, f"Automated Deployment: {len(to_replace)} UV maps updated")
                    if committed:
                        git_helper.git_push(repo_root)
                        st.success(f"Successfully deployed {len(to_replace)} files to GitHub!")
                        st.balloons()
                    else:
                        st.info("No changes were detected by Git to push.")
                except Exception as e:
                    st.error(f"GitHub Deployment failed: {e}")

conn.close()
