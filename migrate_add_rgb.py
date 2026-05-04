import config
import psycopg2
from PIL import Image
import numpy as np
from io import BytesIO

def calculate_average_rgb(image_bytes):
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    arr = np.array(img)
    avg_r = float(np.mean(arr[:,:,0]))
    avg_g = float(np.mean(arr[:,:,1]))
    avg_b = float(np.mean(arr[:,:,2]))
    return avg_r, avg_g, avg_b

def run_migration():
    print("Starting database migration to add RGB columns...")
    conn = None
    try:
        conn = config.get_db_connection()
        cursor = conn.cursor()

        # 1. Add new columns if they don't exist
        print("Checking for existing RGB columns...")
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'processed_image_data' AND column_name IN ('avg_r', 'avg_g', 'avg_b')")
        existing_cols = [row[0] for row in cursor.fetchall()]

        if 'avg_r' not in existing_cols:
            print("Adding avg_r column...")
            cursor.execute("ALTER TABLE processed_image_data ADD COLUMN avg_r REAL")
        if 'avg_g' not in existing_cols:
            print("Adding avg_g column...")
            cursor.execute("ALTER TABLE processed_image_data ADD COLUMN avg_g REAL")
        if 'avg_b' not in existing_cols:
            print("Adding avg_b column...")
            cursor.execute("ALTER TABLE processed_image_data ADD COLUMN avg_b REAL")
        conn.commit()
        print("Columns added/verified.")
        cursor.close()

        # 2. Back-fill existing data (one by one to handle transaction aborts)
        print("Back-filling RGB values for existing images...")
        
        while True:
            cursor = conn.cursor()
            cursor.execute("SELECT hash, storage_key_processed FROM processed_image_data WHERE avg_r IS NULL AND storage_key_processed IS NOT NULL LIMIT 1")
            row = cursor.fetchone()
            cursor.close()
            
            if not row:
                break
                
            img_hash, storage_key = row
            print(f"Processing: {img_hash}...")
            
            try:
                # Download from Supabase
                image_data = config.supabase_storage_client.storage.from_("cleaned_images").download(storage_key)
                if not image_data:
                    print(f"  [Skipped] Failed to download data for {img_hash}.")
                    # Set a dummy value to avoid infinite loop
                    cursor = conn.cursor()
                    cursor.execute("UPDATE processed_image_data SET avg_r=-1 WHERE hash=%s", (img_hash,))
                    conn.commit()
                    cursor.close()
                    continue
                    
                avg_r, avg_g, avg_b = calculate_average_rgb(image_data)

                cursor = conn.cursor()
                cursor.execute("UPDATE processed_image_data SET avg_r=%s, avg_g=%s, avg_b=%s WHERE hash=%s",
                               (avg_r, avg_g, avg_b, img_hash))
                conn.commit()
                cursor.close()
                print(f"  Updated RGB.")
            except Exception as e:
                print(f"  Error: {e}")
                conn.rollback() # Important: Rollback on error to clear aborted state

        print("RGB back-fill complete.")

    except Exception as e:
        print(f"An error occurred during migration: {e}")
    finally:
        if conn: conn.close()
        print("Database connection closed.")

if __name__ == "__main__":
    run_migration()