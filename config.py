from pathlib import Path
from datetime import datetime

# ---------------- Root Paths ----------------
ROOT_DIR = Path(__file__).parent  # adjust if config.py is inside a subfolder
IMAGE_PROCESSING_DIR = ROOT_DIR / "Image Processing"

# ---------------- Stage 0 / 1 Paths ----------------
RAW_DIR = IMAGE_PROCESSING_DIR / "1_Raw"          # raw images
CLEANED_DIR = IMAGE_PROCESSING_DIR / "2_Cleaned"  # processed / cleaned images
STITCHED_DIR = IMAGE_PROCESSING_DIR / "3_Stitched"  # final stitched output

# ---------------- Database ----------------
DB_DIR = IMAGE_PROCESSING_DIR / "Databases"  # folder where DBs are stored
DB_DIR.mkdir(exist_ok=True, parents=True)    # ensure folder exists
DB_PATH = DB_DIR / "image_data.db"          # new DB file
GALLERY_UVS_DIR = ROOT_DIR / "Gallery UVs" # UVs are here

# ---------------- Token ----------------
TOKEN_FILE = ROOT_DIR / ".gitignore" / "token.txt"
TOKEN = TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else ""

# ---------------- Image Processing Constants ----------------
OUTPUT_SIZE = 2048         # target UV map size for batches
TOLERANCE = 5              # black border threshold
ASPECT_CATEGORIES = ["Extra Tall", "Portrait", "Square", "Landscape", "Extra Wide"]

# ---------------- Aspect Codes (for naming / stitching) ----------------
ASPECT_CODES = {
    "Square": "SQ",
    "Extra Tall": "ET",
    "Extra Wide": "EW",
    "Landscape": "LS",
    "Portrait": "PT"
}

# ---------------- Default Stitching Naming ----------------
ROOM_CODES = ["MG", "SR"]  # room codes
DEFAULT_POSITION = "01"    # default slot in UV map grid

# ---------------- Discord Bot Settings (EDIT THESE) ----------------
CHANNEL_ID = 1455106973052702770   # <-- EDIT: your Discord channel ID
DOWNLOAD_RETRIES = 2               # optional: number of download attempts per attachment
BATCH_COMMIT_SIZE = 1              # optional: commit to DB every N images
TESTING_MODE = True                # <-- EDIT: True=dry run, False=save images & DB writes

# ---------------- Optional Date Range for Message Processing (EDIT THESE) ----------------
SEARCH_AFTER = datetime(2026, 2, 1, 0, 0)   # <-- EDIT: set a datetime to start processing from
SEARCH_BEFORE = None  # set to datetime(...) if you want an end date
