# WattNode Desktop GUI

A cross-platform desktop application to run WattNode and earn WATT.

![WattNode GUI](assets/screenshot.png)

## Quick Start (Windows)

### Option 1: Download Installer (Recommended)
1. Download `WattNode-Setup.exe` from [Releases](https://github.com/WattCoin-Org/wattcoin/releases)
2. Run installer → Next → Install
3. Launch WattNode from desktop shortcut

### Option 2: Run from Source
```powershell
cd wattnode
pip install -r requirements_gui.txt
python wattnode_gui.py
```

## Quick Start (Linux)

### Option 1: Run from Source
```bash
# Ubuntu/Debian prerequisites
sudo apt update && sudo apt install -y python3-tk

# Clone and run
git clone https://github.com/WattCoin-Org/wattcoin.git
cd wattcoin/wattnode
pip3 install -r requirements_gui.txt
python3 wattnode_gui.py
```

### Option 2: Build Binary
```bash
cd wattnode
python3 build_linux.py
chmod +x dist/WattNode
./dist/WattNode
```

## Building the Executable

### Windows
- Requires [PyInstaller](https://pyinstaller.org/)
- Run `python build_windows.py`
- Output: `dist/WattNode.exe`
- (Optional) Use [Inno Setup](https://jrsoftware.org/isdl.php) with `installer.iss` for installer creation

### Linux
- Requires [PyInstaller](https://pyinstaller.org/)
- Run `python3 build_linux.py`
- Output: `dist/WattNode`

## Features

- ⚡ **One-click start/stop** - No command line needed
- 🧠 **AI Inference Support** - Tweak blocks, models, and serving status
- 🔍 **GPU Detection** - Integrated NVIDIA monitoring via `nvidia-smi`
- 📊 **Live stats** - Jobs completed, WATT earned
- 🎨 **Dark theme** - Matches WattCoin branding

## Files

| File | Description |
|------|-------------|
| `wattnode_gui.py` | Main GUI application |
| `build_windows.py` | Windows PyInstaller script |
| `build_linux.py` | Linux PyInstaller script |
| `requirements_gui.txt` | GUI dependencies |
| `requirements_inference.txt` | WSI Inference dependencies |

## Color Palette

Matches wattcoin.org:
- Background: `#0f0f0f`
- Surface: `#1a1a1a`
- Accent: `#39ff14` (neon green)
- Text: `#ffffff`
