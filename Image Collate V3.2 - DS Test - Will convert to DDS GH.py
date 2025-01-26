import os
import csv
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageOps, ImageEnhance
import imagehash
import numpy as np
from collections import defaultdict
import imageio  # For DDS conversion

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("image_processing.log"),
        logging.StreamHandler()
    ]
)

def get_perceptual_hash(image):
    """Generate a perceptual hash of the image using phash."""
    return imagehash.phash(image)

def get_dominant_color(image):
    """Calculate the average color of the image."""
    image = image.resize((50, 50))  # Resize to speed up calculation
    pixels = np.array(image)
    avg_color = np.mean(pixels, axis=(0, 1))  # Average RGB values
    return tuple(avg_color)

def calculate_whiteness(image, threshold=240):
    """Calculate the proportion of white pixels in the image."""
    pixels = np.array(image)
    white_pixels = np.sum(np.all(pixels >= threshold, axis=-1))  # Count white pixels
    total_pixels = pixels.shape[0] * pixels.shape[1]
    whiteness_ratio = white_pixels / total_pixels
    return whiteness_ratio

def calculate_blackness(image, threshold=30):
    """Calculate the proportion of black pixels in the image."""
    pixels = np.array(image)
    black_pixels = np.sum(np.all(pixels <= threshold, axis=-1))  # Count black pixels
    total_pixels = pixels.shape[0] * pixels.shape[1]
    blackness_ratio = black_pixels / total_pixels
    return blackness_ratio

def preprocess_image(image):
    """Apply preprocessing steps like normalization and histogram equalization."""
    # Normalize image
    image = ImageOps.autocontrast(image)
    # Enhance sharpness
    enhancer = ImageEnhance.Sharpness(image)
    image = enhancer.enhance(1.5)
    return image

def process_image(filename, subcategory_path, image_size, processed_images):
    """Process a single image and return its data or log errors."""
    input_path = os.path.join(subcategory_path, filename)
    try:
        image = Image.open(input_path)
        image = image.resize(image_size)
        image = preprocess_image(image)  # Apply preprocessing
        dominant_color = get_dominant_color(image)
        whiteness = calculate_whiteness(image)
        blackness = calculate_blackness(image)
        perceptual_hash = get_perceptual_hash(image)
        if perceptual_hash in processed_images:
            logging.warning(f"Duplicate image found: {filename}")
            return None, filename, True  # Return None for image, filename, and duplicate flag
        return (image, dominant_color, whiteness, blackness, filename), filename, False
    except Exception as e:
        logging.error(f"Error processing {filename}: {e}")
        return None, filename, False

def process_images_in_parallel(available_images, subcategory_path, image_size, processed_images):
    """Process images in parallel using ThreadPoolExecutor."""
    images = []
    duplicates = []
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_image, filename, subcategory_path, image_size, processed_images) for filename in available_images]
        for future in as_completed(futures):
            result, filename, is_duplicate = future.result()
            if is_duplicate:
                duplicates.append(filename)
            elif result:
                images.append(result)
    return images, duplicates

def load_processed_images(log_csv_path):
    """Load previously processed images and their hashes from a CSV log."""
    processed_images = {}
    if os.path.exists(log_csv_path):
        with open(log_csv_path, 'r', newline='') as file:
            reader = csv.reader(file)
            next(reader, None)  # Skip header
            for row in reader:
                perceptual_hash = row[3]  # Perceptual hash is the 4th column
                batch_number = int(row[2])  # Batch number is the 3rd column
                processed_images[perceptual_hash] = batch_number
    return processed_images

def write_log_to_csv(log_csv_path, log_entries):
    """Write the log entries to the CSV file."""
    file_exists = os.path.exists(log_csv_path)
    with open(log_csv_path, 'a', newline='') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(["Category", "Subcategory", "Batch Number", "Perceptual Hash", "Image Filename"])
        writer.writerows(log_entries)

def group_images_by_blackness_whiteness_and_color(images):
    """
    Group images by their blackness (darker images at the bottom),
    then whiteness (lighter images at the top), and finally by dominant color similarity.
    """
    # Sort by blackness (descending), then whiteness (ascending), then dominant color similarity
    images.sort(key=lambda x: (-x[3], x[2], np.linalg.norm(np.array(x[1]) - np.array([128, 128, 128]))))
    return images

def convert_to_dds(image_path, output_path):
    """Convert an image to DDS format using imageio."""
    try:
        image = imageio.imread(image_path)
        imageio.imwrite(output_path, image, format="DDS")
        logging.info(f"Converted {image_path} to {output_path}")
    except Exception as e:
        logging.error(f"Error converting {image_path} to DDS: {e}")

def process_category(input_dir, output_path, category, grid_size, image_size, processed_images, log_entries, category_summaries):
    """Process all images in a category."""
    category_path = os.path.join(input_dir, category)
    if not os.path.isdir(category_path):
        logging.warning(f"Skipping {category} because the category directory does not exist.")
        return category_summaries

    subcategories = [subcategory for subcategory in os.listdir(category_path) if os.path.isdir(os.path.join(category_path, subcategory))]
    if not any(subcategory == 'main' for subcategory in subcategories):
        subcategories.append('main')

    # Initialize category summary counters
    category_summaries[category] = {
        "Images in folder": 0,
        "Checked": 0,
        "Duplicates found": 0,
        "Processed": 0,
        "Stitched batches": 0,
        "Duplicate files": []  # Track duplicate filenames
    }

    for subcategory in subcategories:
        subcategory_path = os.path.join(category_path, subcategory)
        if subcategory == 'main':
            subcategory_path = category_path
            logging.info(f"Processing images directly from {category} folder under 'main' subcategory.")

        available_images = [f for f in os.listdir(subcategory_path) if os.path.isfile(os.path.join(subcategory_path, f)) and f.lower().endswith((".png", ".jpg", ".jpeg"))]

        if not available_images:
            logging.warning(f"No images found in {subcategory} folder. Skipping.")
            continue

        category_summaries[category]["Images in folder"] += len(available_images)

        processed_in_category = 0
        checked_in_category = 0
        duplicates_in_category = 0
        stitched_in_category = 0

        batch_number = 1  # Track batch number incrementally
        all_images = []  # This will store images as (image, dominant_color, whiteness, blackness, filename)

        while available_images:
            batch_log = []
            logging.info(f"Checking for duplicates and loading images in {subcategory_path}...")

            images = []
            while len(images) < grid_size[0] * grid_size[1] and available_images:
                filename = available_images.pop(0)
                input_path = os.path.join(subcategory_path, filename)
                checked_in_category += 1

                try:
                    image = Image.open(input_path)
                    image = image.resize(image_size)
                    dominant_color = get_dominant_color(image)
                    whiteness = calculate_whiteness(image)
                    blackness = calculate_blackness(image)

                    # Check if perceptual hash is already in processed_images (i.e., duplicate detection)
                    perceptual_hash = get_perceptual_hash(image)
                    if perceptual_hash in processed_images:
                        logging.warning(f"Duplicate image found: {filename}. It will be ignored.")
                        duplicates_in_category += 1
                        category_summaries[category]["Duplicate files"].append(filename)  # Add to duplicate list
                        continue

                    images.append((image, dominant_color, whiteness, blackness, filename))  # Store image with its dominant color, whiteness, blackness
                    batch_log.append((category, subcategory, batch_number, str(perceptual_hash), filename))

                    # Add the perceptual hash to the processed images tracker
                    processed_images[perceptual_hash] = batch_number

                except Exception as e:
                    logging.error(f"Error processing {filename}: {e}")

            if not images:
                break

            # Group images by blackness, whiteness, and color similarity
            images = group_images_by_blackness_whiteness_and_color(images)

            # Skip the batch if there are not enough images to fill the grid
            if len(images) < grid_size[0] * grid_size[1]:
                logging.warning(f"Not enough images for a full batch. Skipping batch {batch_number}. Remaining: {len(images)}")
                continue

            # Stitch the grouped images
            logging.info(f"Stitching batch {batch_number}...")

            # Only increment the batch number if there are enough images to form a full batch
            grid_width = grid_size[1] * image_size[0]
            grid_height = grid_size[0] * image_size[1]
            stitched_image = Image.new('RGB', (grid_width, grid_height))

            for j, (img, _, _, _, _) in enumerate(images[:grid_size[0] * grid_size[1]]):  # Only take as many as the grid can hold
                row, col = divmod(j, grid_size[1])
                x_offset = col * image_size[0]
                y_offset = row * image_size[1]
                stitched_image.paste(img, (x_offset, y_offset))

            # Save the stitched image as PNG
            stitched_image_name = f"{category}-{subcategory}-{batch_number}.png"
            stitched_image_path = os.path.join(output_path, stitched_image_name)
            stitched_image.save(stitched_image_path)

            # Convert the stitched image to DDS
            dds_image_name = f"{category}-{subcategory}-{batch_number}.dds"
            dds_image_path = os.path.join(output_path, dds_image_name)
            convert_to_dds(stitched_image_path, dds_image_path)

            log_entries.extend(batch_log)
            category_summaries[category]["Stitched batches"] += 1
            processed_in_category += len(images)
            stitched_in_category += 1

            # Now increment batch number after successful stitching
            batch_number += 1  # Increment batch number only after stitching

            logging.info(f"Batch {batch_number - 1} stitched and saved as {stitched_image_name} and {dds_image_name}.")

        # Update category summary with subcategory-specific counts
        category_summaries[category]["Checked"] += checked_in_category
        category_summaries[category]["Duplicates found"] += duplicates_in_category
        category_summaries[category]["Processed"] += processed_in_category

        # Update subcategory summary counters
        category_summaries[category][subcategory] = {
            "Images in folder": len(available_images),
            "Checked": checked_in_category,
            "Duplicates found": duplicates_in_category,
            "Processed": processed_in_category,
            "Stitched batches": stitched_in_category
        }

    return category_summaries

def stitch_images(input_dir, output_path, log_csv_path, grid_size=(4, 4), image_size=(512, 512)):
    """Main function to stitch images."""
    try:
        processed_images = load_processed_images(log_csv_path)
        log_entries = []
        category_summaries = {}

        categories = [category for category in os.listdir(input_dir) if os.path.isdir(os.path.join(input_dir, category))]

        for category in categories:
            category_summaries = process_category(input_dir, output_path, category, grid_size, image_size, processed_images, log_entries, category_summaries)

        write_log_to_csv(log_csv_path, log_entries)

        # Summary
        logging.info("\nSummary Report")
        logging.info("=" * 40)
        total_checked = 0
        total_duplicates = 0
        total_processed = 0
        total_stitched = 0

        for category, stats in category_summaries.items():
            logging.info(f"\nCategory: {category}")
            for subcategory, substats in stats.items():
                if isinstance(substats, dict):
                    logging.info(f"  Subcategory: {subcategory}")
                    logging.info(f"    Images in folder: {substats['Images in folder']}")
                    logging.info(f"    Checked: {substats['Checked']}")
                    logging.info(f"    Duplicates found: {substats['Duplicates found']}")
                    logging.info(f"    Processed: {substats['Processed']}")
                    logging.info(f"    Stitched batches: {substats['Stitched batches']}")
                    if substats.get('Duplicate files'):
                        logging.info(f"    Duplicate files: {', '.join(substats['Duplicate files'])}")

                    # Accumulate totals
                    total_checked += substats['Checked']
                    total_duplicates += substats['Duplicates found']
                    total_processed += substats['Processed']
                    total_stitched += substats['Stitched batches']

        # Display overall summary
        logging.info("\nOverall Summary")
        logging.info("=" * 40)
        logging.info(f"Total images checked: {total_checked}")
        logging.info(f"Total duplicates found: {total_duplicates}")
        logging.info(f"Total images processed: {total_processed}")
        logging.info(f"Total stitched batches: {total_stitched}")
        logging.info("=" * 40)

    except Exception as e:
        logging.error(f"Unexpected error encountered: {e}")
    finally:
        # Pause at the end to keep the window open
        input("Press Enter to exit...")

# Example usage
if __name__ == "__main__":
    input_directory = r"C:\Users\Sabbo\LifeDrawingGallery\Processed"
    output_directory = r"C:\Users\Sabbo\LifeDrawingGallery\UV Maps"
    log_csv_path = r"C:\Users\Sabbo\LifeDrawingGallery\UV Maps\stitched_images_log.csv"

    stitch_images(input_directory, output_directory, log_csv_path)