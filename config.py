from pathlib import Path
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from supabase import create_client, Client # Import Supabase client

# Load environment variables from .env file
load_dotenv()

# Helper to grab from Streamlit secrets first, then OS environ
def get_secret(key):
    try:
        import streamlit as st
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key)

# ---------------- Root Paths ----------------
ROOT_DIR = Path(__file__).parent
IMAGE_PROCESSING_DIR = ROOT_DIR / "Image Processing"

# ---------------- Stage 0 / 1 Paths ----------------
RAW_DIR = IMAGE_PROCESSING_DIR / "1_Raw"
CLEANED_DIR = IMAGE_PROCESSING_DIR / "2_Cleaned"
STITCHED_DIR = IMAGE_PROCESSING_DIR / "3_Stitched"

RAW_DIR.mkdir(parents=True, exist_ok=True)
CLEANED_DIR.mkdir(parents=True, exist_ok=True)

# ---------------- Database (Cloud) ----------------
DB_URL = get_secret("DB_URL")

def get_db_connection():
    """Returns a connection to the Supabase Postgres database."""
    if not DB_URL:
        raise ValueError("DB_URL not found in Streamlit secrets or .env file. Please set it up.")
    try:
        conn = psycopg2.connect(DB_URL)
        return conn
    except psycopg2.OperationalError as e:
        print(f"ERROR: Failed to connect to database: {e}")
        raise

# Legacy DB Path (kept for reference or local temp tasks)
DB_DIR = IMAGE_PROCESSING_DIR / "Databases"
DB_PATH = DB_DIR / "image_data.db"
GALLERY_UVS_DIR = ROOT_DIR / "Gallery UVs"

# ---------------- Token ----------------
TOKEN = get_secret("DISCORD_TOKEN")
if not TOKEN:
    TOKEN_FILE = ROOT_DIR / ".gitignore" / "token.txt" # Keeping your old path logic
    TOKEN = TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else ""

# ---------------- Image Processing Constants ----------------
OUTPUT_SIZE = 2048
TOLERANCE = 5
ASPECT_CATEGORIES = ["Extra Tall", "Portrait", "Square", "Landscape", "Extra Wide"]

ASPECT_CODES = {
    "Square": "SQ",
    "Extra Tall": "ET",
    "Extra Wide": "EW",
    "Landscape": "LS",
    "Portrait": "PT"
}

ROOM_CODES = ["MG", "SR"]
DEFAULT_POSITION = "01"

# ---------------- Discord Bot Settings ----------------
# Old single channel default removed, now using categories
_gen_channel = get_secret("DISCORD_CHANNEL_ID")
_gen_channel = int(_gen_channel) if _gen_channel else 1455106973052702770

CHANNEL_CATEGORIES = {
    1057838318307524608: "Abstract",
    1057879266647343144: "Fan-Art",
    957560752791769168: "Nature",
    1057838072638738492: "Portraits",
    1422792963439984642: "Still-Life",
    1343515047103827978: "Life-Drawing-Prompts",
    _gen_channel: "General"
}

DOWNLOAD_RETRIES = 2
BATCH_COMMIT_SIZE = 1
TESTING_MODE = True # Default to True for safety

# ---------------- Emoji Config ----------------
ACCEPT_EMOJI = "✅"
DUPLICATE_EMOJI = "⚠️"
VETO_EMOJI = "❌"
INVALID_EMOJI = "❌"

# ---------------- Search Range ----------------
SEARCH_AFTER = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
SEARCH_BEFORE = None  # Up to now

# ---------------- Supabase Storage Client ----------------
SUPABASE_URL = get_secret("SUPABASE_URL")
# Accept either ANON_KEY or service role KEY
SUPABASE_ANON_KEY = get_secret("SUPABASE_ANON_KEY") or get_secret("SUPABASE_KEY")

supabase_storage_client = None

def initialize_storage_client():
    global supabase_storage_client
    if SUPABASE_URL and SUPABASE_ANON_KEY:
        try:
            supabase_storage_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
            print("[Config] Supabase Storage client initialized successfully.")
        except Exception as e:
            print(f"[Config] Error initializing Supabase Storage client: {e}")
            supabase_storage_client = None
    else:
        print("[Config] SUPABASE_URL or SUPABASE_ANON_KEY not found in .env. Supabase Storage will not be available.")
        supabase_storage_client = None

initialize_storage_client()

# Ensure RAW_DIR, CLEANED_DIR, STITCHED_DIR exist (local cache for storage operations)
RAW_DIR.mkdir(parents=True, exist_ok=True)
CLEANED_DIR.mkdir(parents=True, exist_ok=True)
STITCHED_DIR.mkdir(parents=True, exist_ok=True)

# ---------------- Supabase Storage Helpers ----------------
def upload_to_supabase(file_path: Path, bucket_name: str, object_key: str = None):
    """Uploads a file to Supabase Storage."""
    if not supabase_storage_client:
        print("[Storage] Supabase Storage client not initialized.")
        return None
    try:
        file_content = file_path.read_bytes()
        ext = file_path.suffix.lower()
        if ext == ".jpeg": ext = ".jpg"
        if not object_key:
            object_key = f"{file_path.stem}{ext}"

        print(f"[Storage] Uploading {file_path.name} to bucket '{bucket_name}' as '{object_key}'...")
        upload_result = supabase_storage_client.storage.from_(bucket_name).upload(
            path=object_key,
            file=file_content,
            file_options={"content-type": f"image/{ext[1:]}", "upsert": "true"}
        )
        if hasattr(upload_result, 'json'): # PostgrestResponse
            res_json = upload_result.json()
            if isinstance(res_json, dict) and "Key" in res_json:
                return object_key
        # Check standard dict return for supbase-py < 2.0 or 2.0
        if isinstance(upload_result, dict) and upload_result.get("Key"):
            return object_key
        elif isinstance(upload_result, dict) and upload_result.get("path"):
            return object_key
        # For newer supabase-py versions, it might just succeed or raise exception
        return object_key
    except Exception as e:
        print(f"[Storage] Error uploading {file_path.name}: {e}")
        return None

def download_from_supabase(object_key: str, local_dir: Path, bucket_name: str):
    """Downloads a file from Supabase Storage to a local directory."""
    if not supabase_storage_client:
        print("[Storage] Supabase Storage client not initialized.")
        return None
    try:
        print(f"[Storage] Downloading {object_key} from bucket '{bucket_name}' to {local_dir}...")
        local_file_path = local_dir / object_key
        local_file_path.parent.mkdir(parents=True, exist_ok=True)

        download_result = supabase_storage_client.storage.from_(bucket_name).download(object_key)
        
        # Handle byte response
        if isinstance(download_result, bytes):
            with open(local_file_path, "wb") as f:
                f.write(download_result)
            return local_file_path
        elif hasattr(download_result, 'read'):
            with open(local_file_path, "wb") as f:
                f.write(download_result.read())
            return local_file_path
        else:
            print(f"[Storage] Download failed or returned unexpected result type: {type(download_result)}")
            return None
    except Exception as e:
        print(f"[Storage] Error downloading {object_key}: {e}")
        return None

