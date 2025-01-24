import os
from PIL import Image
import numpy as np

def debug_image(image_path):
    """
    This function inspects the image and prints detailed debug information
    to help identify why the bounding box might not be working correctly.
    It also calculates and prints the aspect ratio of the bounding box.
    """
    print(f"Debugging image: {image_path}")
    
    try:
        # Open the image
        image = Image.open(image_path)
        
        # Convert RGBA to RGB if necessary
        if image.mode == 'RGBA':
            image = image.convert('RGB')
        
        # Convert to numpy array for easier manipulation
        image_np = np.array(image)
        
        # Print basic image properties
        print(f"Image size: {image.size}")
        print(f"Image mode: {image.mode}")
        print(f"Image shape: {image_np.shape}")
        
        # Check the unique values in the image (to see the variety of pixel values)
        unique_values = np.unique(image_np.reshape(-1, image_np.shape[2]), axis=0)
        print(f"Unique pixel values in image (first 10): {unique_values[:10]}")
        
        # Check the shape of the mask for non-black pixels
        mask = np.any(image_np != [0, 0, 0], axis=-1) if len(image_np.shape) == 3 else (image_np != 0)
        print(f"Mask shape: {mask.shape}")
        
        # Display the coordinates of non-black pixels
        coords = np.argwhere(mask)
        if coords.size > 0:
            print(f"Found non-black pixels at the following coordinates (first 10): {coords[:10]}")
        else:
            print("No non-black pixels found.")
        
        # If there are non-black pixels, calculate the bounding box and aspect ratio
        if coords.size > 0:
            x0, y0 = coords.min(axis=0)
            x1, y1 = coords.max(axis=0) + 1  # +1 to include the last row/column
            print(f"Calculated bounding box: Top-left({x0}, {y0}), Bottom-right({x1}, {y1})")
            
            # Calculate the aspect ratio of the bounding box
            bbox_width = y1 - y0
            bbox_height = x1 - x0
            aspect_ratio = bbox_width / bbox_height if bbox_height != 0 else 0
            print(f"Bounding box aspect ratio: {aspect_ratio:.2f} (Width/Height)")
            
            # Visualize the bounding box by drawing it on the image
            debug_image = image.copy()
            from PIL import ImageDraw
            draw = ImageDraw.Draw(debug_image)
            draw.rectangle([y0, x0, y1, x1], outline="red", width=3)
            debug_image.show()

    except Exception as e:
        print(f"Error debugging {image_path}: {e}")

def debug_directory(input_dir):
    """
    Apply the debug function to all images in the specified directory.
    """
    print(f"Starting to debug images in directory: {input_dir}")

    for filename in os.listdir(input_dir):
        input_path = os.path.join(input_dir, filename)
        if os.path.isfile(input_path) and filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            debug_image(input_path)

# Directory containing the images
input_directory = r"C:\Users\Sabbo\Pictures\VRC Painting Archive\Raw"

# Apply debug to all images in the directory
debug_directory(input_directory)

# Pause at the end
input("Press Enter to exit...")
