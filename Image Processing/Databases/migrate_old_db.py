import sqlite3
from pathlib import Path
from datetime import datetime

def migrate_old_db():
    # ---------------- Paths ----------------
    SCRIPT_DIR = Path(__file__).parent
    OLD_DB_PATH = SCRIPT_DIR / "old.db"
    NEW_DB_PATH = SCRIPT_DIR / "image_data.db"

    logs = []

    def log(msg):
        print(msg)
        logs.append(msg)

    log(f"[Migration] Old DB: {OLD_DB_PATH}")
    log(f"[Migration] New DB: {NEW_DB_PATH}")

    if not OLD_DB_PATH.exists():
        log("[Error] Old DB not found! Place 'old.db' in the same folder as this script.")
        input("Press Enter to exit...")
        return

    # ---------------- Connect to old DB ----------------
    old_conn = sqlite3.connect(OLD_DB_PATH)
    old_cursor = old_conn.cursor()

    # ---------------- Connect / create new DB ----------------
    new_conn = sqlite3.connect(NEW_DB_PATH)
    new_cursor = new_conn.cursor()

    # ---------------- Ensure raw_image_data table exists ----------------
    new_cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_image_data (
            hash TEXT PRIMARY KEY,
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
    new_conn.commit()
    log("[DB] Ensured 'raw_image_data' table exists in new DB.")

    # ---------------- Read from old DB ----------------
    # Determine actual columns in old DB
    old_cursor.execute("PRAGMA table_info(images)")
    columns = [row[1] for row in old_cursor.fetchall()]
    log(f"[DB] Old DB columns: {columns}")

    # Fetch only columns that exist
    select_cols = [col for col in ['hash','phash','user_id','username','message_id','channel_id','original_filename','created_at'] if col in columns]
    old_cursor.execute(f"SELECT {', '.join(select_cols)} FROM images")
    rows = old_cursor.fetchall()
    log(f"[Migration] Found {len(rows)} rows in old DB. Migrating...")

    # ---------------- Insert into raw_image_data ----------------
    migrated = 0
    for row in rows:
        row_dict = dict(zip(select_cols, row))
        created_at = row_dict.get('created_at') or datetime.now().isoformat()
        new_cursor.execute(
            "INSERT OR IGNORE INTO raw_image_data (hash, phash, poster_id, poster_name, "
            "message_id, channel_id, original_filename, created_at, processing, batched) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0)",
            (
                row_dict.get('hash'),
                row_dict.get('phash'),
                row_dict.get('user_id') or row_dict.get('poster_id'),
                row_dict.get('username') or row_dict.get('poster_name'),
                row_dict.get('message_id'),
                row_dict.get('channel_id'),
                row_dict.get('original_filename'),
                created_at
            )
        )
        migrated += 1

    new_conn.commit()
    log(f"[Migration] Completed! Migrated {migrated} rows into 'raw_image_data'.")

    old_conn.close()
    new_conn.close()

    log("Migration finished successfully.")
    input("Press Enter to exit...")

# ---------------- Entry Point ----------------
if __name__ == "__main__":
    migrate_old_db()
