# process_stage1.py
import config
from pathlib import Path
from PIL import Image
import numpy as np
import imagehash
import hashlib
from datetime import datetime, timezone
import os

# ---------------- Config ----------------
RAW_DIR = config.RAW_DIR
PROCESSED_DIR = config.CLEANED_DIR
TOLERANCE = config.TOLERANCE

# Ensure local cache dirs exist
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# ---------------- Helpers ----------------
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def trim_black_border(arr, tol, line_frac=0.85):
    """Return a content box (x0, y0, x1, y1) after trimming near-black borders.

    Trims contiguous rows/columns inward from each edge where at least
    ``line_frac`` of the pixels are near-black (all channels <= ``tol``). Unlike
    a min/max bounding box of non-black pixels, this is robust to a few stray
    bright pixels in the border (signatures, JPEG noise, specks) that would
    otherwise defeat the crop entirely.
    """
    dark = np.all(arr <= tol, axis=-1)
    row_dark = dark.mean(axis=1)
    col_dark = dark.mean(axis=0)

    def trim(profile):
        n = len(profile)
        lo = 0
        while lo < n and profile[lo] >= line_frac:
            lo += 1
        hi = n
        while hi > lo and profile[hi - 1] >= line_frac:
            hi -= 1
        return lo, hi

    y0, y1 = trim(row_dark)
    x0, x1 = trim(col_dark)
    return int(x0), int(y0), int(x1), int(y1)

def is_duplicate(cursor, original_hash, phash):
    cursor.execute("""
        SELECT 1 FROM processed_image_data
        WHERE original_hash=%s OR phash=%s
    """, (original_hash, phash))
    return cursor.fetchone() is not None

def already_stitched(cursor, original_hash):
    cursor.execute("""
        SELECT 1
        FROM images
        WHERE hash=%s AND is_stitched=1
        LIMIT 1
    """, (original_hash,))
    return cursor.fetchone() is not None

def run_processing(progress_callback=None):
    """Run Stage 1 against every raw_image_data row with processing=0.

    progress_callback(current, total, filename) — optional, called after each
    image so callers (e.g. Streamlit) can render a progress bar.

    Returns a summary dict: {success, skipped_duplicates, failed, total}.
    """
    conn = config.get_db_connection()
    cursor = conn.cursor()

    # Fetch DB records
    cursor.execute("""
        SELECT hash, modified_hash, storage_key_raw, original_filename, needs_crop
        FROM raw_image_data
        WHERE processing = 0 AND veto = 0 AND storage_key_raw IS NOT NULL
    """)
    db_records = cursor.fetchall()

    if not db_records:
        print("No images found to process.")
        conn.close()
        return {'success': 0, 'skipped_duplicates': 0, 'failed': [], 'total': 0}

    print(f"Total images queued: {len(db_records)}")

    success_count = 0
    skipped_duplicates = 0
    failed = []

    for idx, row in enumerate(db_records):
        original_hash = row[0]
        active_hash = row[1] if row[1] else row[0]
        storage_key = row[2]
        filename = row[3] or f"{active_hash}.jpg"
        was_manually_cropped = not row[4]  # needs_crop=0 means user already handled it

        print(f"Processing {filename}...")

        try:
            local_path = RAW_DIR / storage_key
            if not local_path.exists():
                config.download_from_supabase(storage_key, RAW_DIR, "raw_images")
            
            if not local_path.exists():
                print(f"  Failed to download {storage_key}")
                failed.append(filename)
                continue

            image = Image.open(local_path)
            img_phash = str(imagehash.phash(image))

            if is_duplicate(cursor, original_hash, img_phash) and already_stitched(cursor, original_hash):
                print(f"  Skipping duplicate: {filename}")
                skipped_duplicates += 1
                cursor.execute("UPDATE raw_image_data SET processing=1 WHERE hash=%s", (original_hash,))
                conn.commit()
                continue

            if image.mode == 'RGBA': image = image.convert('RGB')
            arr = np.array(image)

            # Trim near-black borders by edge profile (robust to stray bright pixels).
            x0, y0, x1, y1 = trim_black_border(arr, TOLERANCE)

            if x1 <= x0 or y1 <= y0:
                print(f"  Empty image (all black?) after border trim: {filename}")
                failed.append(filename)
                continue

            # If almost nothing was trimmed, no meaningful black border was found.
            # Skip re-flagging if the user already manually cropped it — trust their edit.
            if (x1-x0 >= image.width*0.98 and y1-y0 >= image.height*0.98):
                if was_manually_cropped:
                    print(f"  No border found but manually cropped — proceeding as-is: {filename}")
                    x0, y0, x1, y1 = 0, 0, image.width, image.height
                else:
                    print(f"  No significant black border found, flagging for manual crop: {filename}")
                    cursor.execute("UPDATE raw_image_data SET needs_crop=1 WHERE hash=%s", (original_hash,))
                    conn.commit()
                    continue

            cropped = image.crop((x0,y0,x1,y1))

            w,h = cropped.size
            ratio = w/h
            if ratio < 0.6: category="Extra Tall"
            elif ratio < 0.9: category="Portrait"
            elif ratio <= 1.1: category="Square"
            elif ratio <= 1.8: category="Landscape"
            else: category="Extra Wide"

            sizes = {"Square":(512,512), "Portrait":(512,717), "Extra Tall":(512,1024), "Landscape":(717,512), "Extra Wide":(1024,512)}
            target_w,target_h = sizes[category]
            resized = cropped.resize((target_w,target_h), Image.Resampling.LANCZOS)

            output_dir = PROCESSED_DIR / category
            output_dir.mkdir(parents=True, exist_ok=True)
            
            out_filename = f"{active_hash}.jpg"
            out_path = output_dir / out_filename
            resized.save(out_path, format="JPEG")

            processed_hash = sha256_bytes(out_path.read_bytes())
            processed_phash = str(imagehash.phash(resized))

            # Calculate average RGB
            arr_resized = np.array(resized)
            avg_r = float(np.mean(arr_resized[:,:,0]))
            avg_g = float(np.mean(arr_resized[:,:,1]))
            avg_b = float(np.mean(arr_resized[:,:,2]))

            # Upload to Cloud
            processed_storage_key = config.upload_to_supabase(out_path, "cleaned_images")

            if processed_storage_key:
                cursor.execute("SELECT 1 FROM processed_image_data WHERE hash=%s", (processed_hash,))
                if not cursor.fetchone():
                    cursor.execute("""
                        INSERT INTO processed_image_data (
                            hash, phash, original_hash, original_filename,
                            category, width, height, created_at, storage_key_processed,
                            avg_r, avg_g, avg_b
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        processed_hash, processed_phash, original_hash, filename, 
                        category, target_w, target_h, datetime.now(timezone.utc), 
                        processed_storage_key, avg_r, avg_g, avg_b
                    ))

                cursor.execute("UPDATE raw_image_data SET processing=1 WHERE hash=%s", (original_hash,))
                print(f"  Successfully processed and uploaded: {out_filename}")
                success_count += 1
                
                # Cleanup local files
                try: 
                    local_path.unlink()
                    out_path.unlink()
                except: pass
            else:
                print(f"  Upload failed for {out_filename}")
                failed.append(f"{filename} (Upload Failed)")

        except Exception as e:
            print(f"  Error processing {filename}: {e}")
            failed.append(filename)

        conn.commit()

        if progress_callback:
            try:
                progress_callback(idx + 1, len(db_records), filename)
            except Exception as cb_err:
                print(f"  (progress callback error: {cb_err})")

    print("\nProcessing complete")
    print(f"Processed successfully: {success_count}")
    print(f"Duplicates skipped: {skipped_duplicates}")
    if failed: print(f"Failed images: {failed}")

    conn.close()
    return {
        'success': success_count,
        'skipped_duplicates': skipped_duplicates,
        'failed': failed,
        'total': len(db_records),
    }

if __name__ == "__main__":
    run_processing()
