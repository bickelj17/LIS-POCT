"""
Build the distributable zip for teammates.
Run: python build_dist.py
Creates: LIS_POCT_Analysis.zip (in this folder)
"""
import zipfile
from pathlib import Path

FILES = [
    "app.py",
    "poct_checks.py",
    "poct_line_checks.py",
    "requirements.txt",
    "run.bat",
    "README.txt",
]
ZIP_NAME = "LIS_POCT_Analysis.zip"

def main():
    root = Path(__file__).resolve().parent
    zip_path = root / ZIP_NAME
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in FILES:
            path = root / name
            if path.exists():
                zf.write(path, name)
                print(f"  Added: {name}")
            else:
                print(f"  Skip (missing): {name}")
    print(f"\n  Created: {zip_path}")
    print(f"  Send {ZIP_NAME} to teammates. They unzip and double-click run.bat.")

if __name__ == "__main__":
    main()
