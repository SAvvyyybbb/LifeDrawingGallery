import subprocess
import os
from wand.image import Image

# Function to test ImageMagick command-line usage
def test_imagemagick_cli():
    try:
        # Test if ImageMagick 'convert' command is available
        print("Testing ImageMagick command-line...")
        result = subprocess.run(["convert", "-version"], capture_output=True, text=True)
        if result.returncode == 0:
            print("ImageMagick is installed and working!")
            print(result.stdout)  # Print version info
        else:
            print("ImageMagick is not installed or not in PATH.")
            print(result.stderr)
    except FileNotFoundError:
        print("ImageMagick command-line tool not found. Please ensure it's installed and in your PATH.")

# Function to test Wand (ImageMagick's Python binding)
def test_wand():
    try:
        print("\nTesting Wand (Python binding for ImageMagick)...")
        
        # Ensure the test image exists in the current directory
        test_image_path = "test_image.png"
        if not os.path.exists(test_image_path):
            print(f"Test image '{test_image_path}' not found, creating a sample image.")
            
            # Create a simple image using Wand to test
            with Image(width=200, height=100, background='white') as img:
                img.caption("Test Image", left=50, top=40)
                img.save(filename=test_image_path)

        # Open the image with Wand and convert it to DDS
        with Image(filename=test_image_path) as img:
            img.format = 'dds'
            img.save(filename="test_image_output.dds")
            print("Image converted successfully to DDS format using Wand!")

    except Exception as e:
        print(f"An error occurred with Wand: {e}")

# Run the tests
test_imagemagick_cli()
test_wand()
