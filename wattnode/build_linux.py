#!/usr/bin/env python3
"""
Build WattNode Linux Executable
Requires: pip install pyinstaller pillow

Run: python3 build_linux.py
Output: dist/WattNode
"""

import os
import subprocess
import sys
import shutil

def main():
    print("=" * 50)
    print("WattNode Linux Build")
    print("=" * 50)
    
    # Check dependencies
    try:
        import PyInstaller
        print("✓ PyInstaller found")
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    try:
        from PIL import Image
        print("✓ Pillow found")
    except ImportError:
        print("Installing Pillow...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pillow"])
    
    # Create assets folder
    os.makedirs("assets", exist_ok=True)
    
    # PyInstaller command
    cmd = [
        "pyinstaller",
        "--onefile",
        "--windowed",  # No console window (requires X11/Wayland)
        "--name=WattNode",
        "--add-data=assets:assets",  # Include assets folder (colon on Linux)
    ]
    
    # Add icon if exists
    if os.path.exists("assets/logo.png"):
        cmd.append("--icon=assets/logo.png")
    
    cmd.append("wattnode_gui.py")
    
    print("\nRunning PyInstaller...")
    print(" ".join(cmd))
    print()
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print("\n" + "=" * 50)
        print("✓ Build successful!")
        print("=" * 50)
        print("\nOutput: dist/WattNode")
        
        # Check for appimagetool to create AppImage
        appimagetool = shutil.which("appimagetool")
        if appimagetool:
            print("\nCreating AppImage...")
            # (Basic AppImage creation logic would go here)
            print("Note: AppImage creation requires a .desktop file and AppDir structure.")
        
        print("\nNext steps:")
        print("1. Set executable permission: chmod +x dist/WattNode")
        print("2. Run: ./dist/WattNode")
    else:
        print("\n✗ Build failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
