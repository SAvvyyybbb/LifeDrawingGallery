import streamlit as st
import discord
import aiohttp
import hashlib
import sqlite3
from datetime import datetime, timezone, time
from pathlib import Path
import asyncio
import threading
import io
from PIL import Image
import imagehash
import traceback
import config
import nest_asyncio
from streamlit_autorefresh import st_autorefresh

# ---------------- Setup ----------------
nest_asyncio.apply()  # Allows nested asyncio loops

BASE_DIR = config.RAW_DIR
INBOX_DIR = BASE_DIR  # All images go here
DB_PATH = config.DB_DIR / "discord_scraper.db"

CHANNEL_ID = 1455106973052702770
DOWNLOAD_RETRIES = 2

# ---------------- Streamlit Session State ----------------
if "scraper_log" not in st.session_state:
    st.session_state.scraper_log = []

if "stop_scraper" not in st.session_state:
    st.session_state.stop_scraper = False

# ---------------- Thread-safe log buffer ----------------
log_buffer = []

def log(msg):
    """Add log to thread-safe buffer."""
    log_buffer.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def flush_log():
    """Push buffered logs to Streamlit UI."""
    for entry in log_buffer:
        st.session_state.scraper_log.append(entry)
    log_buffer.clear()
    log_box.text_area("Scraper Log / Status", value="\n".join(st.session_state.scraper_log), height=400)

# ---------------- Helpers ----------------
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def normalize_extension(ext: str) -> str:
    ext = ext.lower()
    if ext == ".jpeg":
        return ".jpg"
    return ext

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS images (
            hash TEXT PRIMARY KEY,
            phash TEXT,
            user_id INTEGER,
            username TEXT,
            message_id INTEGER,
            channel_id INTEGER,
            original_filename TEXT,
            shortdate_uploaded TEXT,
            first_downloaded TEXT,
            batched INTEGER DEFAULT 0,
            in_processing INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    return conn, cursor

def get_last_message_id(cursor):
    cursor.execute("SELECT value FROM metadata WHERE key='last_message_id'")
    row = cursor.fetchone()
    return int(row[0]) if row else None

def set_last_message_id(cursor, conn, message_id):
    cursor.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        ('last_message_id', str(message_id))
    )
    conn.commit()

# ---------------- Phash Cache ----------------
class PhashCache:
    def __init__(self, cursor):
        self.cache = []
        cursor.execute("SELECT hash, phash FROM images")
        for row in cursor.fetchall():
            self.cache.append((row[0], imagehash.hex_to_hash(row[1])))

    def add(self, img_phash, img_hash=None):
        self.cache.append((img_hash, img_phash))

# ---------------- Discord Bot ----------------
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# ---------------- Main scraper logic ----------------
async def main_logic(token, start_after=None, end_before=None):
    try:
        await client.login(token)
        log("Logged in successfully.")
    except Exception:
        log("[ERROR] Failed to log in with Discord token.")
        return

    INBOX_DIR.mkdir(parents=True, exist_ok=True)

    conn, cursor = init_db()
    phash_cache = PhashCache(cursor)
    last_message_id = get_last_message_id(cursor)
    after_message = discord.Object(id=last_message_id) if last_message_id else None

    total_messages = total_images = total_skipped_processing = total_skipped_batched = total_invalid = 0
    batch_commit_count = 0

    if start_after:
        start_after = datetime.combine(start_after, time.min, tzinfo=timezone.utc)
    if end_before:
        end_before = datetime.combine(end_before, time.max, tzinfo=timezone.utc)

    async with aiohttp.ClientSession() as session:
        try:
            channel = await client.fetch_channel(CHANNEL_ID)
            if not channel:
                log("[ERROR] Channel not found or no access.")
                return

            async for msg in channel.history(limit=None, oldest_first=True, after=after_message):
                if st.session_state.stop_scraper:
                    log("[INFO] Stop requested by user.")
                    break

                total_messages += 1

                if start_after and msg.created_at < start_after:
                    continue
                if end_before and msg.created_at > end_before:
                    continue

                for att in msg.attachments:
                    if not att.content_type or not att.content_type.startswith("image") or \
                       not att.filename.lower().endswith((".png", ".jpg", ".jpeg")):
                        total_invalid += 1
                        continue

                    data = None
                    for _ in range(DOWNLOAD_RETRIES):
                        try:
                            async with session.get(att.url) as r:
                                if r.status == 200:
                                    data = await r.read()
                                    break
                        except Exception:
                            await asyncio.sleep(0.5)
                    if data is None:
                        total_invalid += 1
                        continue

                    img_hash = sha256_bytes(data)
                    try:
                        image = Image.open(io.BytesIO(data))
                        img_phash = imagehash.phash(image)
                    except Exception:
                        total_invalid += 1
                        continue

                    # Check DB for existing hash
                    cursor.execute("SELECT in_processing, batched FROM images WHERE hash=?", (img_hash,))
                    row = cursor.fetchone()

                    ext = normalize_extension(Path(att.filename).suffix or ".img")
                    filename = f"{img_hash}{ext}"
                    inbox_path = INBOX_DIR / filename

                    if row:
                        in_processing, batched = row
                        if batched == 1:
                            log(f"[INFO] Image {att.filename} ({img_hash}) already batched. Skipping.")
                            total_skipped_batched += 1
                            continue
                        if in_processing == 1:
                            log(f"[INFO] Image {att.filename} ({img_hash}) currently in processing. Skipping.")
                            total_skipped_processing += 1
                            continue
                        # Update existing row
                        inbox_path.write_bytes(data)
                        cursor.execute("""
                            UPDATE images
                            SET first_downloaded=?, user_id=?, username=?, message_id=?, channel_id=?, original_filename=?, shortdate_uploaded=?
                            WHERE hash=?
                        """, (
                            datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                            msg.author.id,
                            str(msg.author),
                            msg.id,
                            msg.channel.id,
                            att.filename,
                            msg.created_at.strftime("%Y-%m-%d"),
                            img_hash
                        ))
                        log(f"[INFO] Exact duplicate {att.filename} ({img_hash}) updated in DB.")
                    else:
                        # New image → insert row
                        inbox_path.write_bytes(data)
                        shortdate_uploaded = msg.created_at.strftime("%Y-%m-%d")
                        first_downloaded = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                        cursor.execute("""
                            INSERT INTO images (
                                hash, phash, user_id, username, message_id, channel_id,
                                original_filename, shortdate_uploaded, first_downloaded,
                                batched, in_processing
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (img_hash, str(img_phash), msg.author.id, str(msg.author),
                              msg.id, msg.channel.id, att.filename,
                              shortdate_uploaded, first_downloaded, 0, 0))
                        phash_cache.add(img_phash, img_hash)
                        log(f"[INFO] New image {att.filename} ({img_hash}) downloaded and added to DB.")

                    total_images += 1
                    batch_commit_count += 1
                    await asyncio.sleep(0)

                set_last_message_id(cursor, conn, msg.id)

                if batch_commit_count >= 10:
                    conn.commit()
                    batch_commit_count = 0
                    log(f"[INFO] Committed batch of images. Total images so far: {total_images}")
                    await asyncio.sleep(0)

        except Exception:
            log("[ERROR] An unexpected exception occurred:")
            log(traceback.format_exc())
        finally:
            conn.commit()
            conn.close()
            log(f"[INFO] Scraper finished. Total messages: {total_messages}, new images: {total_images}, skipped processing: {total_skipped_processing}, skipped batched: {total_skipped_batched}")

    await client.close()

# ---------------- Streamlit UI ----------------
st.title("Discord Image Scraper")

start_after = st.date_input("Start Date")
end_before = st.date_input("End Date")

log_box = st.empty()  # Placeholder for live log display

# ---------------- Run scraper in background thread ----------------
def run_scraper(token, start_after, end_before):
    asyncio.run(main_logic(token, start_after, end_before))

if st.button("Start Scraper"):
    st.session_state.stop_scraper = False
    token = st.secrets["discord"]["bot_token"]  # Correct secrets access
    threading.Thread(target=run_scraper, args=(token, start_after, end_before), daemon=True).start()

if st.button("Force Stop Scraper"):
    st.session_state.stop_scraper = True
    log("[INFO] Stop requested by user.")

# ---------------- Auto-refresh log ----------------
# Refresh every 1 second
st_autorefresh(interval=1000, key="log_refresh")
flush_log()
