import os
import time
import csv
from PIL import Image

def get_corner_pixels(image):
    pixels = image.load()
    width, height = image.size
    return (
        pixels[0, 0],  # Top-left
        pixels[width - 1, 0],  # Top-right
        pixels[0, height - 1],  # Bottom-left
        pixels[width - 1, height - 1]  # Bottom-right
    )

def create_composite_key(filename, corners):
    return f"{filename}_{corners[0]}_{corners[1]}_{corners[2]}_{corners[3]}"

def load_processed_images(log_csv_path):
    processed_images = {}
    if os.path.exists(log_csv_path):
        with open(log_csv_path, 'r', newline='') as file:
            reader = csv.reader(file)
            next(reader, None)  # Skip header
            for row in reader:
                composite_key = row[0]
                batch_number = int(row[1])
                processed_images[composite_key] = batch_number
    return processed_images

def write_log_to_csv(log_csv_path, log_entries):
    file_exists = os.path.exists(log_csv_path)
    with open(log_csv_path, 'a', newline='') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(["Composite Key", "Batch Number"])
        writer.writerows(log_entries)

def process_category(input_dir, output_path, category, grid_size, image_size, processed_images, log_entries, category_summaries):
    category_path = os.path.join(input_dir, category)

    # Ensure that we check if the category path exists before proceeding
    if not os.path.isdir(category_path):
        print(f"Skipping {category} because the category directory does not exist.")
        return category_summaries

    # Find subcategories, if any
    subcategories = [subcategory for subcategory in os.listdir(category_path) if os.path.isdir(os.path.join(category_path, subcategory))]

    # Initialize summary counters for each category
    category_summaries[category] = {
        "Images in folder": 0,
        "Checked": 0,
        "Duplicates found": 0,
        "Processed": 0,
        "Stitched batches": 0
    }

    # If no subcategories are found, process images directly from the main category
    if not subcategories:
        print(f"No subcategories found in {category}. Processing images directly from the category folder.")
        available_images = [f for f in os.listdir(category_path) if os.path.isfile(os.path.join(category_path, f)) and f.lower().endswith((".png", ".jpg", ".jpeg"))]
        
        # Check if images are found in the main category folder
        if not available_images:
            print(f"No images found in the main category folder {category}. Skipping.")
            category_summaries[category]["Images in folder"] = 0
            category_summaries[category]["Checked"] = 0
            category_summaries[category]["Duplicates found"] = 0
            category_summaries[category]["Processed"] = 0
            category_summaries[category]["Stitched batches"] = 0
            return category_summaries

        # Process images in the main category folder (as no subcategories exist)
        subcategories = [category]  # Treat the main category as the only subcategory

    # Loop through subcategories (or the main category if no subcategories exist)
    for subcategory in subcategories:
        subcategory_path = os.path.join(category_path, subcategory)

        # If no subcategories are found, process the category folder directly
        if not os.path.isdir(subcategory_path):
            subcategory_path = category_path  # Use the category path itself
            print(f"Processing images directly from {category} folder.")

        # Look for image files in the subcategory directory (or in the main category if no subcategories)
        available_images = [f for f in os.listdir(subcategory_path) if os.path.isfile(os.path.join(subcategory_path, f)) and f.lower().endswith((".png", ".jpg", ".jpeg"))]

        # If there are no images, skip this subcategory or main category
        if not available_images:
            print(f"No images found in {subcategory} folder. Skipping.")
            continue

        # Track category statistics
        category_summaries[category]["Images in folder"] += len(available_images)

        processed_in_category = 0
        checked_in_category = 0
        duplicates_in_category = 0
        stitched_in_category = 0

        while available_images:
            images = []
            batch_log = []
            print(f"Checking for duplicates and loading images in {subcategory_path}...")

            while len(images) < grid_size[0] * grid_size[1] and available_images:
                filename = available_images.pop(0)
                input_path = os.path.join(subcategory_path, filename)
                checked_in_category += 1

                try:
                    image = Image.open(input_path)
                    image = image.resize(image_size)
                    corners = get_corner_pixels(image)
                    composite_key = create_composite_key(filename, corners)

                    # Check if image is a duplicate across all categories
                    if composite_key in processed_images:
                        print(f"Duplicate image found: {filename}. It will be ignored.")
                        duplicates_in_category += 1
                        continue

                    print(f"Processing image: {filename}")
                    images.append(image)
                    batch_log.append((composite_key, processed_images.get(composite_key, 0) + 1))

                except Exception as e:
                    print(f"Error processing {filename}: {e}")

            if not images:
                break

            if len(images) < grid_size[0] * grid_size[1]:
                print(f"Not enough images for a full batch. Remaining: {len(images)}")
                break

            print(f"Stitching batch {len(batch_log)}...")
            grid_width = grid_size[1] * image_size[0]
            grid_height = grid_size[0] * image_size[1]
            stitched_image = Image.new('RGB', (grid_width, grid_height))

            for i in range(grid_size[0]):
                for j in range(grid_size[1]):
                    index = i * grid_size[1] + j
                    x_offset = j * image_size[0]
                    y_offset = i * image_size[1]
                    stitched_image.paste(images[index], (x_offset, y_offset))

            timestamp = time.strftime("%Y-%m-%d-%H-%M-%S")
            stitched_image_name = f"{category}-{subcategory}-Batch-{len(batch_log)}-{timestamp}.png"
            stitched_image.save(os.path.join(output_path, stitched_image_name))

            log_entries.extend(batch_log)
            category_summaries[category]["Stitched batches"] += 1
            processed_in_category += len(images)
            stitched_in_category += 1

            print(f"Batch {len(batch_log)} stitched and saved as {stitched_image_name}.")

        # Save statistics for this subcategory or the main category (if no subcategories)
        category_summaries[category][subcategory] = {
            "Images in folder": len(available_images),
            "Checked": checked_in_category,
            "Duplicates found": duplicates_in_category,
            "Processed": processed_in_category,
            "Stitched batches": stitched_in_category
        }

    return category_summaries


def stitch_images(input_dir, output_path, log_csv_path, grid_size=(4, 4), image_size=(512, 512)):
    try:
        duplicate_count = 0
        batch_count = 0
        duplicate_files = []
        processed_images = load_processed_images(log_csv_path)
        log_entries = []
        category_summaries = {}

        categories = [category for category in os.listdir(input_dir) if os.path.isdir(os.path.join(input_dir, category))]

        for category in categories:
            category_summaries = process_category(input_dir, output_path, category, grid_size, image_size, processed_images, log_entries, category_summaries)

        write_log_to_csv(log_csv_path, log_entries)

        # Summary
        print("\nSummary Report")
        print("=" * 40)
        for category, stats in category_summaries.items():
            print(f"\nCategory: {category}")
            for subcategory, substats in stats.items():
                if isinstance(substats, dict):
                    print(f"  Subcategory: {subcategory}")
                    print(f"    Images in folder: {substats['Images in folder']}")
                    print(f"    Checked: {substats['Checked']}")
                    print(f"    Duplicates found: {substats['Duplicates found']}")
                    print(f"    Processed: {substats['Processed']}")
                    print(f"    Stitched batches: {substats['Stitched batches']}")
        print("=" * 40)

        # Pause at the end to keep the window open
        input("Press Enter to exit...")

    except Exception as e:
        print(f"Unexpected error encountered: {e}")
        input("Press Enter to exit and view the error log...")

# Input and output paths
input_directory = r"C:\Users\Sabbo\LifeDrawingGallery\Processed"
output_directory = r"C:\Users\Sabbo\LifeDrawingGallery\UV Maps"
log_csv_path = r"C:\Users\Sabbo\LifeDrawingGallery\UV Maps\stitched_images_log.csv"

try:
    # Run the stitching process
    stitch_images(input_directory, output_directory, log_csv_path)

except Exception as e:
    print(f"An error occurred: {e}")
    input("Press Enter to exit and view the error log...")
