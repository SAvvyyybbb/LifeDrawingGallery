import os
import tkinter as tk
from tkinter import messagebox
from PIL import Image
import logging

try:
    import pydds
except ImportError:
    pydds = None

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

# Set up logging
log_file = "conversion_log.txt"
logging.basicConfig(filename=log_file, level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logging.info("Script started.")

# Directory paths
input_dir = r"C:\Users\Sabbo\LifeDrawingGallery\UV Maps"
output_dir = r"C:\Users\Sabbo\LifeDrawingGallery\Converted"

# Create output directory if it doesn't exist
if not os.path.exists(output_dir):
    os.makedirs(output_dir)
    logging.info(f"Created output directory: {output_dir}")

# Dependency Check
def check_dependencies():
    missing = []
    if not pydds:
        missing.append("pydds")
    if not tqdm:
        missing.append("tqdm")
    if missing:
        logging.error(f"Missing dependencies: {', '.join(missing)}")
        messagebox.showerror(
            "Missing Dependencies",
            f"The following Python modules are missing: {', '.join(missing)}. Install them and try again.",
        )
        return False
    return True

# Convert PNG to DDS
def convert_png_to_dds(input_path, output_path):
    try:
        logging.info(f"Converting: {input_path} -> {output_path}")
        with Image.open(input_path) as img:
            dds_image = pydds.PyDDS(img)  # Convert to DDS using pydds
            dds_image.save(output_path)
        logging.info(f"Successfully converted: {input_path}")
        return True
    except Exception as e:
        logging.error(f"Error converting {input_path}: {e}")
        return False

# GUI Application
class ConversionApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PNG to DDS Converter")
        self.label = tk.Label(root, text="PNG to DDS Converter", font=("Arial", 16))
        self.label.pack(pady=10)
        
        self.progress_label = tk.Label(root, text="Progress: 0%", font=("Arial", 12))
        self.progress_label.pack(pady=5)
        
        self.start_button = tk.Button(root, text="Start Conversion", command=self.start_conversion, font=("Arial", 12))
        self.start_button.pack(pady=10)
        
        self.quit_button = tk.Button(root, text="Quit", command=self.quit_app, font=("Arial", 12))
        self.quit_button.pack(pady=10)

    def update_progress(self, percentage):
        self.progress_label.config(text=f"Progress: {percentage}%")

    def start_conversion(self):
        # Check dependencies
        if not check_dependencies():
            return
        
        # Validate input directory
        if not os.path.exists(input_dir):
            messagebox.showerror("Error", f"Input directory does not exist: {input_dir}")
            logging.error(f"Input directory not found: {input_dir}")
            return
        
        # Find PNG files
        png_files = [f for f in os.listdir(input_dir) if f.lower().endswith('.png')]
        if not png_files:
            messagebox.showinfo("No Files", "No PNG files found in the input directory.")
            logging.warning("No PNG files found in the directory.")
            return

        # Start Conversion
        total_files = len(png_files)
        successful_conversions = 0
        for i, png_file in enumerate(png_files):
            input_path = os.path.join(input_dir, png_file)
            output_path = os.path.join(output_dir, png_file.replace('.png', '.dds'))
            
            if convert_png_to_dds(input_path, output_path):
                successful_conversions += 1
            
            # Update progress
            progress_percentage = int(((i + 1) / total_files) * 100)
            self.update_progress(progress_percentage)
        
        # Show summary
        summary = f"Conversion complete: {successful_conversions}/{total_files} files successfully converted."
        logging.info(summary)
        messagebox.showinfo("Summary", summary)

    def quit_app(self):
        self.root.quit()

# Run the application
if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = ConversionApp(root)
        root.mainloop()
    except Exception as e:
        logging.critical(f"Unexpected error: {e}")
        print(f"Unexpected error: {e}")
    finally:
        logging.info("Script ended.")
        print("Check the log file for details.")
        input("Press Enter to exit...")
