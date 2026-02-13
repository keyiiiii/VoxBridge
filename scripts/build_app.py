#!/usr/bin/env python3
"""Build VoxBridge.app macOS application bundle.

Creates a self-contained .app that runs from ~/Library/Application Support/VoxBridge/
to avoid macOS TCC (Files and Folders) restrictions on Documents/Desktop/Downloads.

Usage:
    python scripts/build_app.py          # Build to dist/VoxBridge.app
    python scripts/build_app.py --install  # Also copy to /Applications
"""

import argparse
import os
import plistlib
import shutil
import stat
import subprocess
import sys

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
APP_NAME = "VoxBridge"
BUNDLE_ID = "com.voxbridge.app"
VERSION = "0.1.0"

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(PROJECT_DIR, "dist")
APP_PATH = os.path.join(DIST_DIR, f"{APP_NAME}.app")
APP_SUPPORT = os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")


# ---------------------------------------------------------------------------
# Icon generation (using AppKit)
# ---------------------------------------------------------------------------
def generate_icon(output_icns: str) -> None:
    """Generate a simple app icon."""
    from AppKit import (
        NSBezierPath,
        NSBitmapImageRep,
        NSColor,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSImage,
        NSMakeRect,
        NSPNGFileType,
    )
    from Foundation import NSAttributedString, NSDictionary

    iconset_dir = os.path.join(DIST_DIR, f"{APP_NAME}.iconset")
    os.makedirs(iconset_dir, exist_ok=True)

    entries = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }

    for filename, size in entries.items():
        img = NSImage.alloc().initWithSize_((size, size))
        img.lockFocus()

        # Background: rounded rectangle
        bg = NSColor.colorWithRed_green_blue_alpha_(0.28, 0.15, 0.70, 1.0)
        bg.setFill()
        radius = size * 0.22
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(0, 0, size, size), radius, radius
        ).fill()

        # Inner glow
        inner = NSColor.colorWithRed_green_blue_alpha_(0.45, 0.30, 0.90, 0.3)
        inner.setFill()
        inset = size * 0.08
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(inset, inset, size - inset * 2, size - inset * 2),
            radius * 0.8,
            radius * 0.8,
        ).fill()

        # "VB" text
        font_size = size * 0.38
        attrs = NSDictionary.dictionaryWithDictionary_({
            NSFontAttributeName: NSFont.boldSystemFontOfSize_(font_size),
            NSForegroundColorAttributeName: NSColor.whiteColor(),
        })
        text = NSAttributedString.alloc().initWithString_attributes_("VB", attrs)
        ts = text.size()
        text.drawAtPoint_(((size - ts.width) / 2, (size - ts.height) / 2))

        img.unlockFocus()

        tiff = img.TIFFRepresentation()
        bitmap = NSBitmapImageRep.imageRepWithData_(tiff)
        png = bitmap.representationUsingType_properties_(NSPNGFileType, {})
        png.writeToFile_atomically_(os.path.join(iconset_dir, filename), True)

    subprocess.run(
        ["iconutil", "-c", "icns", iconset_dir, "-o", output_icns],
        check=True,
    )
    shutil.rmtree(iconset_dir)
    print(f"  Icon: {output_icns}")


# ---------------------------------------------------------------------------
# Prepare runtime directory (TCC-safe location)
# ---------------------------------------------------------------------------
def prepare_runtime() -> str:
    """Copy source + venv to ~/Library/Application Support/VoxBridge/.

    This directory is NOT protected by macOS TCC (unlike Documents).
    Returns the runtime directory path.
    """
    print(f"  Runtime dir: {APP_SUPPORT}")

    # Clean previous
    if os.path.exists(APP_SUPPORT):
        shutil.rmtree(APP_SUPPORT)
    os.makedirs(APP_SUPPORT)

    # Copy source code
    shutil.copytree(
        os.path.join(PROJECT_DIR, "voxbridge"),
        os.path.join(APP_SUPPORT, "voxbridge"),
    )

    # Copy config and prompts
    shutil.copy2(
        os.path.join(PROJECT_DIR, "config.yaml"),
        os.path.join(APP_SUPPORT, "config.yaml"),
    )
    shutil.copytree(
        os.path.join(PROJECT_DIR, "prompts"),
        os.path.join(APP_SUPPORT, "prompts"),
    )

    # Create venv and install dependencies
    venv_dir = os.path.join(APP_SUPPORT, "venv")
    print(f"  Creating venv: {venv_dir}")
    subprocess.run(
        [sys.executable, "-m", "venv", venv_dir],
        check=True,
    )

    pip = os.path.join(venv_dir, "bin", "pip")
    req = os.path.join(PROJECT_DIR, "requirements.txt")
    print(f"  Installing dependencies (this may take a minute)...")
    subprocess.run(
        [pip, "install", "-q", "-r", req],
        check=True,
    )
    print(f"  Dependencies installed.")

    return APP_SUPPORT


# ---------------------------------------------------------------------------
# Build .app bundle
# ---------------------------------------------------------------------------
def build_app() -> str:
    """Create VoxBridge.app bundle. Returns path to .app."""
    if os.path.exists(APP_PATH):
        shutil.rmtree(APP_PATH)

    contents = os.path.join(APP_PATH, "Contents")
    macos_dir = os.path.join(contents, "MacOS")
    resources = os.path.join(contents, "Resources")
    os.makedirs(macos_dir)
    os.makedirs(resources)

    # --- Icon ---
    icon_path = os.path.join(resources, "icon.icns")
    generate_icon(icon_path)

    # --- Runtime directory ---
    runtime_dir = prepare_runtime()
    venv_python = os.path.join(runtime_dir, "venv", "bin", "python")
    log_file = os.path.expanduser("~/Library/Logs/VoxBridge.log")

    # --- Info.plist ---
    plist = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": VERSION,
        "CFBundleShortVersionString": VERSION,
        "CFBundleExecutable": APP_NAME,
        "CFBundleIconFile": "icon",
        "CFBundlePackageType": "APPL",
        "LSUIElement": True,
        "LSMinimumSystemVersion": "14.0",
        "NSMicrophoneUsageDescription": (
            "VoxBridge uses the microphone to record your voice for "
            "local speech-to-text conversion. Audio never leaves your Mac."
        ),
    }
    plist_path = os.path.join(contents, "Info.plist")
    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)
    print(f"  Plist: {plist_path}")

    # --- Executable ---
    exec_path = os.path.join(macos_dir, APP_NAME)
    with open(exec_path, "w") as f:
        f.write(f"""\
#!/bin/bash
# VoxBridge launcher - generated by build_app.py
RUNTIME_DIR="{runtime_dir}"
VENV_PYTHON="{venv_python}"
LOG_FILE="{log_file}"

exec > "$LOG_FILE" 2>&1

if [ ! -x "$VENV_PYTHON" ]; then
    osascript -e 'display alert "VoxBridge" message "Runtime not found. Please rebuild:\\n  python scripts/build_app.py" as critical'
    exit 1
fi

export PYTHONUNBUFFERED=1
cd "$RUNTIME_DIR"
exec "$VENV_PYTHON" -m voxbridge --preload
""")
    os.chmod(exec_path, 0o755)
    print(f"  Executable: {exec_path}")

    # Ad-hoc code signing
    subprocess.run(
        ["codesign", "--force", "--sign", "-", APP_PATH],
        check=True,
    )
    print(f"  Signed: ad-hoc")

    # Register with LaunchServices
    ls_register = (
        "/System/Library/Frameworks/CoreServices.framework/"
        "Frameworks/LaunchServices.framework/Support/lsregister"
    )
    subprocess.run([ls_register, "-f", APP_PATH], check=False)
    print(f"  Registered with LaunchServices")

    print(f"  Log: {log_file}")
    print(f"\n  Built: {APP_PATH}")
    return APP_PATH


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=f"Build {APP_NAME}.app")
    parser.add_argument(
        "--install",
        action="store_true",
        help="Copy to /Applications after building",
    )
    args = parser.parse_args()

    print(f"Building {APP_NAME}.app ...")
    os.makedirs(DIST_DIR, exist_ok=True)
    app_path = build_app()

    if args.install:
        dest = f"/Applications/{APP_NAME}.app"
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(app_path, dest)
        print(f"\n  Installed: {dest}")

    print(f"\nDone! Launch with:")
    print(f"  open {app_path}")


if __name__ == "__main__":
    main()
