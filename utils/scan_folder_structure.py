import os
from pathlib import Path

# ---------------- Config ----------------
ROOT_DIR = Path(__file__).parent  # Start from the folder where this script lives

def scan_folder(root_dir: Path, level=0):
    """
    Recursively prints folder structure and files.
    """
    indent = "    " * level
    for item in sorted(root_dir.iterdir()):
        if item.is_dir():
            print(f"{indent}[DIR] {item.name}")
            scan_folder(item, level + 1)
        else:
            print(f"{indent}- {item.name}")

if __name__ == "__main__":
    print(f"Scanning folder structure for: {ROOT_DIR}\n")
    scan_folder(ROOT_DIR)
    print("\nScan complete.")
    input("Press Enter to close this window...")
