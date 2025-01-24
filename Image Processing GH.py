import os
from PIL import Image
import numpy as np

def remove_black_borders_and_resize(image_path, output_path, size=(512, 512), tolerance=5):
    """
    Removes black borders from an image, resizes it to the specified size, 
    and checks for black borders again after resizing.
    
    :param image_path: Path to the input image.
    :param output_path: Path to save the processed image.
    :param size: Tuple (width, height) to resize the output image to.
    :param tolerance: The threshold below which pixel values are considered "black".
    """
    print(f"Starting to process image: {image_path}")
    try:
        # Open the image
        print("Opening the image...")
        image = Image.open(image_path)
        
        # Convert RGBA to RGB if necessary
        if image.mode == 'RGBA':
            image = image.convert('RGB')
        
        image_np = np.array(image)
        print("Image opened successfully.")

        # Find the bounding box of non-black content, considering the tolerance
        print("Calculating the bounding box for non-black content...")
        mask = np.all(image_np > tolerance, axis=-1)
        coords = np.argwhere(mask)

        if coords.size == 0:
            print(f"No non-black content found in {image_path}. Skipping this image.")
            return False  # Indicates an error

        # Get the bounding box
        print("Determining the bounding box coordinates...")
        x0, y0 = coords.min(axis=0)
        x1, y1 = coords.max(axis=0) + 1  # +1 to include the last row/column
        print(f"Bounding box determined: Top-left({x0}, {y0}), Bottom-right({x1}, {y1}).")

        # Check if the bounding box is almost the same as the image size (skip crop if true)
        img_width, img_height = image.size
        bbox_width = x1 - x0
        bbox_height = y1 - y0

        # If the bounding box is close to the image size (e.g., 95% or more of the image), skip cropping
        if bbox_width >= img_width * 0.95 and bbox_height >= img_height * 0.95:
            print(f"Bounding box is nearly the same size as the image. Skipping crop.")
            cropped_image = image
        else:
            print("Cropping the image...")
            cropped_image = image.crop((y0, x0, y1, x1))

        # Resize the image
        print("Resizing the image...")
        resized_image = cropped_image.resize(size, Image.Resampling.LANCZOS)

        # Check for black borders again after resizing
        resized_image_np = np.array(resized_image)
        print("Checking for black borders after resizing...")
        mask_resized = np.all(resized_image_np > tolerance, axis=-1)
        coords_resized = np.argwhere(mask_resized)

        if coords_resized.size == 0:
            print(f"After resizing, the image is entirely black. Skipping this image.")
            return False  # Indicates an error

        # Save the processed image
        print(f"Saving the processed image to {output_path}...")
        resized_image.save(output_path)
        print(f"Image processed and saved successfully: {output_path}")
        
        # Delete the original raw file after processing
        print(f"Deleting the original file: {image_path}")
        os.remove(image_path)

        return True  # Indicates success

    except Exception as e:
        print(f"Error processing {image_path}: {e}")
        return False  # Indicates an error

def process_directory(input_dir, output_dir, size=(512, 512), tolerance=5):
    """
    Processes all images in the input directory, removing black borders and resizing.
    
    :param input_dir: Directory containing input images.
    :param output_dir: Directory to save processed images.
    :param size: Tuple (width, height) to resize the output images to.
    :param tolerance: The threshold below which pixel values are considered "black".
    """
    print(f"Starting to process directory: {input_dir}")
    if not os.path.exists(output_dir):
        print(f"Output directory does not exist. Creating directory: {output_dir}")
        os.makedirs(output_dir)
    else:
        print(f"Output directory exists: {output_dir}")

    # Count the processed images and errors
    processed_count = 0
    error_count = 0
    error_images = []

    for filename in os.listdir(input_dir):
        input_path = os.path.join(input_dir, filename)
        if os.path.isfile(input_path) and filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            print(f"Processing file: {filename}")
            output_path = os.path.join(output_dir, filename)
            success = remove_black_borders_and_resize(input_path, output_path, size, tolerance)
            if success:
                processed_count += 1
            else:
                error_count += 1
                error_images.append(filename)
        else:
            print(f"Skipping non-image file: {filename}")

    print(f"Directory processing complete.")
    print(f"Total images processed: {processed_count}")
    print(f"Total errors encountered: {error_count}")

    if error_count > 0:
        print("Images that encountered errors:")
        for error_image in error_images:
            print(f"- {error_image}")

# Input and output directories
input_directory = r"C:\Users\Sabbo\LifeDrawingGallery\Raw"
output_directory = r"C:\Users\Sabbo\LifeDrawingGallery\Processed"

# Process all images in the directory
process_directory(input_directory, output_directory)
input("Processing complete. Press Enter to exit...")
