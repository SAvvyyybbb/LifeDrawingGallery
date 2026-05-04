import sqlite3
import psycopg2
import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

DB_URL = os.getenv("DB_URL")
SQLITE_DB = "/home/savvy/Documents/Python Projects/LifeDrawingGallery/Image Processing/Databases/image_data.db"

def migrate():
    if not DB_URL or "[YOUR-PASSWORD]" in DB_URL:
        print("ERROR: Please set a valid DB_URL in your .env file.")
        return

    print("Connecting to databases...")
    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = psycopg2.connect(DB_URL)
    pg_cursor = pg_conn.cursor()

    # --- 1. Create Tables in Postgres ---
    print("Creating tables in Supabase...")
    
    schema_queries = [
        """
        CREATE TABLE IF NOT EXISTS raw_image_data (
            hash TEXT PRIMARY KEY,
            modified_hash TEXT,
            phash TEXT,
            poster_id BIGINT,
            poster_name TEXT,
            message_id BIGINT,
            channel_id BIGINT,
            original_filename TEXT,
            created_at TIMESTAMPTZ,
            processing INTEGER DEFAULT 0,
            batched INTEGER DEFAULT 0,
            veto INTEGER DEFAULT 0,
            updated_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS processed_image_data (
            hash TEXT PRIMARY KEY,
            phash TEXT,
            original_hash TEXT,
            original_filename TEXT,
            category TEXT,
            width INTEGER,
            height INTEGER,
            created_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS batches (
            id SERIAL PRIMARY KEY,
            primary_folder TEXT,
            secondary_folder TEXT,
            status TEXT,
            img_w INTEGER,
            img_h INTEGER,
            expected_count INTEGER,
            batch_name TEXT,
            timestamp TEXT,
            uv_storage_key TEXT,
            is_archived INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS images (
            id SERIAL PRIMARY KEY,
            batch_id INTEGER REFERENCES batches(id),
            veto_ind INTEGER DEFAULT 0,
            file_path TEXT UNIQUE,
            is_stitched INTEGER DEFAULT 0,
            aspect_category TEXT,
            manual_order INTEGER,
            img_w INTEGER,
            img_h INTEGER,
            avg_r REAL,
            avg_g REAL,
            avg_b REAL,
            perceptual_hash TEXT,
            hash TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stitched_phashes (
            id SERIAL PRIMARY KEY,
            phash TEXT NOT NULL,
            hash TEXT NOT NULL,
            file_path TEXT NOT NULL,
            batch_id INTEGER,
            stitched_date TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS export_moves (
            id SERIAL PRIMARY KEY,
            image_id INTEGER,
            src_path TEXT NOT NULL,
            dst_path TEXT NOT NULL,
            export_type TEXT,
            export_date TEXT
        )
        """,
        """
        CREATE OR REPLACE VIEW vw_image_publishing_status AS
        SELECT 
            r.hash AS raw_hash,
            r.poster_id,
            r.poster_name,
            r.message_id,
            r.channel_id,
            r.original_filename,
            r.created_at AS submitted_at,
            p.hash AS processed_hash,
            i.id AS image_id,
            i.is_stitched,
            b.id AS batch_id,
            b.batch_name,
            b.status AS batch_status,
            b.uv_storage_key,
            b.is_active,
            b.is_archived
        FROM raw_image_data r
        LEFT JOIN processed_image_data p ON r.hash = p.original_hash
        LEFT JOIN images i ON p.hash = i.hash
        LEFT JOIN batches b ON i.batch_id = b.id;
        """
    ]

    for query in schema_queries:
        pg_cursor.execute(query)
    
    pg_conn.commit()

    # --- 2. Migrate Data ---
    tables = [
        "raw_image_data", "processed_image_data", "metadata", 
        "batches", "images", "stitched_phashes", "export_moves"
    ]

    for table in tables:
        print(f"Migrating table: {table}...")
        sqlite_cursor = sqlite_conn.cursor()
        sqlite_cursor.execute(f"SELECT * FROM {table}")
        rows = sqlite_cursor.fetchall()
        
        if not rows:
            print(f"  No data in {table}.")
            continue

        # Get column names
        cols = rows[0].keys()
        col_names = ", ".join(cols)
        placeholders = ", ".join(["%s"] * len(cols))
        
        # Handle 'id' columns for tables with SERIAL to avoid conflict if we re-run
        # We will use INSERT ... ON CONFLICT DO NOTHING for primary keys
        
        insert_query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
        
        data_to_insert = []
        for row in rows:
            row_tuple = list(row)
            if table == "stitched_phashes":
                # batch_id is index 4 in stitched_phashes (id, phash, hash, file_path, batch_id, stitched_date)
                # It is stored as an 8-byte little-endian blob in SQLite
                if isinstance(row_tuple[4], bytes):
                    row_tuple[4] = int.from_bytes(row_tuple[4], byteorder='little')
            data_to_insert.append(tuple(row_tuple))
        
        try:
            pg_cursor.executemany(insert_query, data_to_insert)
            pg_conn.commit()
            print(f"  Successfully migrated {len(data_to_insert)} rows to {table}.")
        except Exception as e:
            print(f"  Error migrating {table}: {e}")
            pg_conn.rollback()

    # --- 3. Fix Sequences ---
    print("Fixing database sequences...")
    serial_tables = ["batches", "images", "stitched_phashes", "export_moves"]
    for table in serial_tables:
        pg_cursor.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1)) FROM {table}")
    
    pg_conn.commit()
    
    sqlite_conn.close()
    pg_conn.close()
    print("\nMigration Complete! Your data is now in the cloud.")

if __name__ == "__main__":
    migrate()
