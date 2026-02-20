import discord
import aiohttp
import os
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import traceback
import asyncio
from PIL import Image
import imagehash
import io
import config

# ---------------- Configuration ----------------
TESTING_MODE = getattr(config, "TESTING_MODE", True)
TOKEN = getattr(config, "TOKEN", "")
CHANNEL_ID = getattr(config, "CHANNEL_ID", 0)

RAW_DIR = config.RAW_DIR  # 1_Raw folder
DB_PATH = config.DB_DIR / "image_data.db"  # unified DB

DOWNLOAD_RETRIES = getattr(config, "DOWNLOAD_RETRIES", 2)
BATCH_COMMIT_SIZE = getattr(config, "BATCH_COMMIT_SIZE", 10)

ACCEPT_EMOJI = getattr(config, "ACCEPT_EMOJI", "✅")
DUPLICATE_EMOJI = getattr(config, "DUPLICATE_EMOJI", "⚠️")
INVALID_EMOJI = getattr(config, "INVALID_EMOJI", "❌")

SEARCH_AFTER = getattr(config, "SEARCH_AFTER", None)
SEARCH_BEFORE = getattr(config, "SEARCH_BEFORE", None)
if SEARCH_AFTER and SEARCH_AFTER.tzinfo is None:
    SEARCH_AFTER = SEARCH_AFTER.replace(tzinfo=timezone.utc)
if SEARCH_BEFORE and SEARCH_BEFORE.tzinfo is None:
    SEARCH_BEFORE = SEARCH_BEFORE.replace(tzinfo=timezone.utc)

# ---------------- Helpers ----------------
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def normalize_extension(ext: str) -> str:
    ext = ext.lower()
    if ext == ".jpeg":
        return ".jpg"
    return ext

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # raw images table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_image_data (
            hash TEXT PRIMARY KEY,
            modified_hash TEXT,
            phash TEXT,
            poster_id INTEGER,
            poster_name TEXT,
            message_id INTEGER,
            channel_id INTEGER,
            original_filename TEXT,
            created_at TEXT,
            processing INTEGER DEFAULT 0,
            batched INTEGER DEFAULT 0
        )
    """)

    # processed images table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_image_data (
            hash TEXT PRIMARY KEY,
            phash TEXT,
            original_hash TEXT,
            original_filename TEXT,
            category TEXT,
            width INTEGER,
            height INTEGER,
            created_at TEXT
        )
    """)

    # metadata table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    return conn, cursor

def get_last_message_id(cursor):
    if TESTING_MODE or cursor is None:
        return None
    cursor.execute("SELECT value FROM metadata WHERE key='last_message_id'")
    row = cursor.fetchone()
    return int(row[0]) if row else None

def set_last_message_id(cursor, conn, message_id):
    if TESTING_MODE or cursor is None:
        print(f"[DB] TESTING_MODE: Would set last_message_id = {message_id}")
        return
    cursor.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        ('last_message_id', str(message_id))
    )
    conn.commit()

class PhashCache:
    def __init__(self, cursor):
        self.cache = []
        if cursor is None:
            print("[Cache] TESTING_MODE: No DB loaded.")
            return
        cursor.execute("SELECT hash, phash FROM raw_image_data")
        for row in cursor.fetchall():
            self.cache.append((row[0], imagehash.hex_to_hash(row[1])))
        print(f"[Cache] Loaded {len(self.cache)} phashes from DB.")

    def is_duplicate(self, img_phash):
        for _, existing_phash in self.cache:
            if img_phash - existing_phash == 0:
                return True
        return False

    def add(self, img_phash, img_hash=None):
        self.cache.append((img_hash, img_phash))

def get_search_range(last_message_id):
    default_after = datetime(1970, 1, 1, tzinfo=timezone.utc)
    default_before = datetime.now(timezone.utc)
    after = SEARCH_AFTER or default_after
    before = SEARCH_BEFORE or default_before
    after_object = discord.Object(id=last_message_id) if last_message_id else None
    return after_object or after, before

# ---------------- Discord Client ----------------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True  # required to fetch channel
client = discord.Client(intents=intents)

# ---------------- Main Logic ----------------
async def main_logic():
    try:
        await client.wait_until_ready()
        print(f"[Bot] Logged in as {client.user}")

        RAW_DIR.mkdir(parents=True, exist_ok=True)

        conn, cursor = init_db()
        phash_cache = PhashCache(cursor)
        last_message_id = get_last_message_id(cursor)
        after, before = get_search_range(last_message_id)

        total_messages = total_images = total_duplicates = total_invalid = 0
        batch_commit_count = 0

        # ---------------- FIX: get channel ----------------
        channel = client.get_channel(CHANNEL_ID)
        if not channel:
            print(f"[ERROR] Channel ID {CHANNEL_ID} not found or bot lacks access.")
            return

        async with aiohttp.ClientSession() as session:
            async for msg in channel.history(limit=None, oldest_first=True, after=after, before=before):
                msg_time = msg.created_at
                if isinstance(after, datetime) and msg_time < after:
                    continue

                total_messages += 1
                message_saved = message_duplicated = message_invalid = False

                for att in msg.attachments:
                    if not att.content_type or not att.content_type.startswith("image") or \
                       not att.filename.lower().endswith((".png", ".jpg", ".jpeg")):
                        message_invalid = True
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
                        message_invalid = True
                        total_invalid += 1
                        continue

                    img_hash = sha256_bytes(data)
                    try:
                        image = Image.open(io.BytesIO(data))
                        img_phash = imagehash.phash(image)
                    except Exception:
                        message_invalid = True
                        total_invalid += 1
                        continue

                    # Skip if already processed
                    cursor.execute("SELECT processing FROM raw_image_data WHERE hash=?", (img_hash,))
                    row = cursor.fetchone()
                    if row and row[0] == 1:
                        print(f"[Skip] Already processed: {att.filename}")
                        continue

                    # duplicate check
                    if phash_cache.is_duplicate(img_phash):
                        message_duplicated = True
                        total_duplicates += 1
                        continue

                    ext = normalize_extension(os.path.splitext(att.filename)[1] or ".img")
                    filename = f"{img_hash}{ext}"

                    if not TESTING_MODE:
                        (RAW_DIR / filename).write_bytes(data)
                        cursor.execute("""
                            INSERT OR IGNORE INTO raw_image_data (
                                hash, phash, poster_id, poster_name,
                                message_id, channel_id, original_filename, created_at, processing, batched
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                        """, (
                            img_hash, str(img_phash),
                            msg.author.id, str(msg.author),
                            msg.id, msg.channel.id, att.filename,
                            datetime.now(timezone.utc).isoformat()
                        ))

                    phash_cache.add(img_phash, img_hash)
                    message_saved = True
                    total_images += 1
                    batch_commit_count += 1

                # reactions
                if not TESTING_MODE:
                    try:
                        if message_saved:
                            await msg.add_reaction(ACCEPT_EMOJI)
                        elif message_duplicated:
                            await msg.add_reaction(DUPLICATE_EMOJI)
                        elif message_invalid:
                            await msg.add_reaction(INVALID_EMOJI)
                    except (discord.Forbidden, discord.HTTPException):
                        pass

                if not TESTING_MODE and batch_commit_count >= BATCH_COMMIT_SIZE:
                    conn.commit()
                    batch_commit_count = 0

                set_last_message_id(cursor, conn, msg.id)

        if not TESTING_MODE:
            conn.commit()
            conn.close()

        print(f"[Summary] Messages: {total_messages}, New: {total_images}, Duplicates: {total_duplicates}, Invalid: {total_invalid}")

    except Exception:
        print("An unexpected error occurred:")
        traceback.print_exc()

# ---------------- Entry Point ----------------
@client.event
async def on_ready():
    client.loop.create_task(main_logic())

def run_bot():
    if not TOKEN:
        print("ERROR: Bot token is empty.")
        return
    try:
        client.run(TOKEN)
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    run_bot()
