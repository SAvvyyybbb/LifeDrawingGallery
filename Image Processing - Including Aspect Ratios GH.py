import os
from PIL import Image
import numpy as np
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def detect_borders(image_np, tolerance=5):
    """
    Detects consistent black borders around the edges of the image.
    
    :param image_np: Image as a NumPy array.
    :param tolerance: The threshold below which pixel values are considered "black".
    :return: Tuple (left, top, right, bottom) indicating the borders to remove.
    """
    height, width, _ = image_np.shape
    
    # Detect top border
    top = 0
    for row in range(height):
        if np.any(image_np[row, :, :] > tolerance):
            break
        top = row + 1
    
    # Detect bottom border
    bottom = height
    for row in range(height - 1, -1, -1):
        if np.any(image_np[row, :, :] > tolerance):
            break
        bottom = row
    
    # Detect left border
    left = 0
    for col in range(width):
        if np.any(image_np[:, col, :] > tolerance):
            break
        left = col + 1
    
    # Detect right border
    right = width
    for col in range(width - 1, -1, -1):
        if np.any(image_np[:, col, :] > tolerance):
            break
        right = col
    
    return left, top, right, bottom

def categorize_image(cropped_image):
    """
    Categorizes the image based on its aspect ratio after cropping and rounds to the nearest category.
    
    :param cropped_image: PIL Image object (cropped version of the original image).
    :return: Category name ("landscape", "extra_wide", "portrait", "extra_tall", "square").
    """
    width, height = cropped_image.size
    aspect_ratio = width / height

    # Debugging: Log the aspect ratio
    logging.info(f"Aspect ratio: {aspect_ratio:.2f}")

    # Define aspect ratio categories and their midpoints
    categories = {
        "extra_tall": 0.6,  # Midpoint between 0.5 and 0.7
        "portrait": 0.9,    # Midpoint between 0.7 and 1.1
        "square": 1.0,      # Exactly 1:1
        "landscape": 1.75,  # Midpoint between 1.5 and 2.0
        "extra_wide": 2.25  # Midpoint between 2.0 and 2.5
    }

    # Find the nearest category based on the aspect ratio
    nearest_category = min(categories.keys(), key=lambda x: abs(aspect_ratio - categories[x]))
    logging.info(f"Image categorized as: {nearest_category}")
    return nearest_category

def remove_black_borders_and_categorize(image_path, output_path, tolerance=5):
    """
    Removes consistent black borders from an image, categorizes it based on its aspect ratio,
    and saves the cropped image without resizing or deleting the source image.
    
    :param image_path: Path to the input image.
    :param output_path: Path to save the processed image.
    :param tolerance: The threshold below which pixel values are considered "black".
    :return: True if successful, False otherwise.
    """
    logging.info(f"Starting to process image: {image_path}")
    try:
        # Open the image using a with statement to ensure the file handle is closed
        with Image.open(image_path) as image:
            logging.info("Opening the image...")
            
            # Convert RGBA to RGB if necessary
            if image.mode == 'RGBA':
                image = image.convert('RGB')
            
            image_np = np.array(image)
            logging.info("Image opened successfully.")

            # Detect consistent borders
            logging.info("Detecting borders...")
            left, top, right, bottom = detect_borders(image_np, tolerance)
            
            # Check if the borders are significant
            img_width, img_height = image.size
            border_threshold = 0.05  # 5% of the image size
            if (right - left) < img_width * (1 - border_threshold) or (bottom - top) < img_height * (1 - border_threshold):
                logging.info(f"Significant borders detected. Cropping image...")
                cropped_image = image.crop((left, top, right, bottom))
            else:
                logging.info(f"No significant borders detected. Skipping crop.")
                cropped_image = image

            # Categorize the image based on the cropped image's aspect ratio
            category = categorize_image(cropped_image)

            # Save the cropped image to the output path
            logging.info(f"Saving the cropped image to {output_path}...")
            cropped_image.save(output_path)
            logging.info(f"Image processed and saved successfully: {output_path}")
        
        return True  # Indicates success

    except Exception as e:
        logging.error(f"Error processing {image_path}: {e}")
        return False  # Indicates an error

def process_directory(input_dir, output_dir, tolerance=5):
    """
    Processes all images in the input directory, removing black borders and categorizing them.
    Images are saved in separate folders based on their aspect ratio category.
    
    :param input_dir: Directory containing input images.
    :param output_dir: Directory to save processed images.
    :param tolerance: The threshold below which pixel values are considered "black".
    """
    logging.info(f"Starting to process directory: {input_dir}")
    if not os.path.exists(output_dir):
        logging.info(f"Output directory does not exist. Creating directory: {output_dir}")
        os.makedirs(output_dir)

    # Create subdirectories for each category
    categories = ["landscape", "extra_wide", "portrait", "extra_tall", "square"]
    for category in categories:
        category_dir = os.path.join(output_dir, category)
        if not os.path.exists(category_dir):
            logging.info(f"Creating category directory: {category_dir}")
            os.makedirs(category_dir)

    # Count the processed images and errors
    processed_count = 0
    error_count = 0
    error_images = []

    for filename in os.listdir(input_dir):
        input_path = os.path.join(input_dir, filename)
        if os.path.isfile(input_path) and filename.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.tiff')):
            logging.info(f"Processing file: {filename}")
            try:
                # Determine the output path based on the category
                output_path = os.path.join(output_dir, filename)  # Default path
                success = remove_black_borders_and_categorize(input_path, output_path, tolerance)
                if success:
                    processed_count += 1
                else:
                    error_count += 1
                    error_images.append(filename)
            except Exception as e:
                logging.error(f"Error processing {filename}: {e}")
                error_count += 1
                error_images.append(filename)
        else:
            logging.info(f"Skipping non-image file: {filename}")

    logging.info(f"Directory processing complete.")
    logging.info(f"Total images processed: {processed_count}")
    logging.info(f"Total errors encountered: {error_count}")

    if error_count > 0:
        logging.warning("Images that encountered errors:")
        for error_image in error_images:
            logging.warning(f"- {error_image}")

# Input and output directories
input_directory = r"C:\Users\Sabbo\LifeDrawingGallery\Raw"
output_directory = r"C:\Users\Sabbo\LifeDrawingGallery\Processed"

# Process all images in the directory
process_directory(input_directory, output_directory)
input("Processing complete. Press Enter to exit...")