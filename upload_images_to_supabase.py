import os
import config
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def create_bucket_if_missing(bucket_name):
    try:
        buckets = config.supabase_storage_client.storage.list_buckets()
        bucket_names = [b.name for b in buckets]
        if bucket_name not in bucket_names:
            print(f"Creating bucket: {bucket_name}")
            config.supabase_storage_client.storage.create_bucket(bucket_name, {"public": True})
    except Exception as e:
        print(f"Error checking/creating bucket {bucket_name}: {e}")

def main():
    if not config.supabase_storage_client:
        print("Storage client not initialized. Check your credentials.")
        return

    create_bucket_if_missing("raw_images")
    create_bucket_if_missing("cleaned_images")
    
    conn = config.get_db_connection()
    cursor = conn.cursor()

    print("--- Uploading 1_Raw ---")
    raw_files = [f for f in config.RAW_DIR.iterdir() if f.is_file() and f.suffix.lower() in ('.png', '.jpg', '.jpeg')]
    for file_path in raw_files:
        hash_stem = file_path.stem
        # check if it already has a storage key
        cursor.execute("SELECT storage_key_raw FROM raw_image_data WHERE hash=%s OR modified_hash=%s", (hash_stem, hash_stem))
        row = cursor.fetchone()
        if row and row[0]:
            print(f"Skipping {file_path.name}, already has storage_key: {row[0]}")
            continue
            
        print(f"Uploading {file_path.name}...")
        key = config.upload_to_supabase(file_path, "raw_images")
        if key:
            cursor.execute("UPDATE raw_image_data SET storage_key_raw=%s WHERE hash=%s OR modified_hash=%s", (key, hash_stem, hash_stem))
            conn.commit()

    print("--- Uploading 2_Cleaned ---")
    for category_folder in config.CLEANED_DIR.iterdir():
        if not category_folder.is_dir():
            continue
        cleaned_files = [f for f in category_folder.iterdir() if f.is_file() and f.suffix.lower() in ('.png', '.jpg', '.jpeg')]
        for file_path in cleaned_files:
            hash_stem = file_path.stem
            cursor.execute("SELECT storage_key_processed FROM processed_image_data WHERE hash=%s", (hash_stem,))
            row = cursor.fetchone()
            if row and row[0]:
                print(f"Skipping {file_path.name}, already has storage_key: {row[0]}")
                continue
                
            print(f"Uploading {category_folder.name}/{file_path.name}...")
            key = config.upload_to_supabase(file_path, "cleaned_images")
            if key:
                cursor.execute("UPDATE processed_image_data SET storage_key_processed=%s WHERE hash=%s", (key, hash_stem))
                conn.commit()

    conn.close()
    print("Done uploading local assets to Supabase Storage.")

if __name__ == "__main__":
    main()
