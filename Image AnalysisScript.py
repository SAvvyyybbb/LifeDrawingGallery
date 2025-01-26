import os
from PIL import Image
import numpy as np
import logging
import json

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

def analyze_image(image_path):
    """
    Analyzes an image, calculates its bounding box, and provides a detailed description.
    
    :param image_path: Path to the input image.
    :return: Dictionary containing detailed information about the image.
    """
    try:
        # Open the image
        with Image.open(image_path) as image:
            # Convert RGBA to RGB if necessary
            if image.mode == 'RGBA':
                image = image.convert('RGB')
            
            # Get original dimensions
            original_width, original_height = image.size
            original_aspect_ratio = original_width / original_height

            # Convert image to NumPy array for border detection
            image_np = np.array(image)

            # Detect borders
            left, top, right, bottom = detect_borders(image_np)

            # Calculate bounding box dimensions
            bbox_width = right - left
            bbox_height = bottom - top
            bbox_aspect_ratio = bbox_width / bbox_height

            # Determine if the bounding box is significantly smaller than the original image
            border_threshold = 0.05  # 5% of the image size
            has_significant_borders = (bbox_width < original_width * (1 - border_threshold)) or (bbox_height < original_height * (1 - border_threshold))

            # Categorize the image based on the bounding box aspect ratio
            if bbox_aspect_ratio > 2:
                category = "extra_wide"
            elif bbox_aspect_ratio > 1:
                category = "landscape"
            elif bbox_aspect_ratio < 0.5:
                category = "extra_tall"
            else:
                category = "portrait"

            # Prepare detailed description
            description = {
                "filename": os.path.basename(image_path),
                "original_dimensions": {"width": original_width, "height": original_height},
                "original_aspect_ratio": round(original_aspect_ratio, 2),
                "bounding_box": {"left": left, "top": top, "right": right, "bottom": bottom},
                "bounding_box_dimensions": {"width": bbox_width, "height": bbox_height},
                "bounding_box_aspect_ratio": round(bbox_aspect_ratio, 2),
                "has_significant_borders": has_significant_borders,
                "category": category,
            }

            return description

    except Exception as e:
        logging.error(f"Error analyzing {image_path}: {e}")
        return None

def process_directory(input_dir, output_log_path):
    """
    Processes all images in the input directory, analyzes them, and logs the results.
    
    :param input_dir: Directory containing input images.
    :param output_log_path: Path to save the analysis log.
    """
    logging.info(f"Starting to process directory: {input_dir}")

    # List to store analysis results
    analysis_results = []

    # Process each image in the directory
    for filename in os.listdir(input_dir):
        input_path = os.path.join(input_dir, filename)
        if os.path.isfile(input_path) and filename.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.tiff')):
            logging.info(f"Analyzing file: {filename}")
            description = analyze_image(input_path)
            if description:
                analysis_results.append(description)
        else:
            logging.info(f"Skipping non-image file: {filename}")

    # Save analysis results to a JSON log file
    with open(output_log_path, "w") as log_file:
        json.dump(analysis_results, log_file, indent=4)

    logging.info(f"Analysis complete. Results saved to: {output_log_path}")

# Input directory and output log path
input_directory = r"C:\Users\Sabbo\LifeDrawingGallery\Raw"
output_log_path = r"C:\Users\Sabbo\LifeDrawingGallery\analysis_log.json"

# Process all images in the directory
process_directory(input_directory, output_log_path)
input("Processing complete. Press Enter to exit...")