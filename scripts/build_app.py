#!/usr/bin/env python3
"""Build VoxBridge.app macOS application bundle.

Creates a self-contained .app with Python.framework, venv, and source code
bundled inside. No external dependencies on the host filesystem.

Usage:
    python scripts/build_app.py          # Build to dist/VoxBridge.app
    python scripts/build_app.py --install  # Also copy to /Applications
"""

import argparse
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
APP_NAME = "VoxBridge"
BUNDLE_ID = "com.voxbridge.app"
VERSION = "0.1.0"

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(PROJECT_DIR, "dist")
APP_PATH = os.path.join(DIST_DIR, f"{APP_NAME}.app")


# ---------------------------------------------------------------------------
# Icon generation (using AppKit)
# ---------------------------------------------------------------------------
def generate_icon(output_icns: str) -> None:
    """Generate a simple app icon."""
    try:
        _generate_icon_appkit(output_icns)
    except (ImportError, ModuleNotFoundError):
        print("  Icon: skipped (AppKit not available)")


def _generate_icon_appkit(output_icns: str) -> None:
    """Generate icon using AppKit (requires pyobjc)."""
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
# Detect Python framework info from the system
# ---------------------------------------------------------------------------
def _detect_python_info() -> dict:
    """Detect Python framework paths and version from the system Python."""
    base_python = shutil.which("python3") or sys.executable
    result = subprocess.run(
        [base_python, "-c", "\n".join([
            "import sysconfig",
            "fw = sysconfig.get_config_var('PYTHONFRAMEWORKPREFIX') or ''",
            "ver = sysconfig.get_config_var('VERSION')",
            "print(fw)",
            "print(ver)",
        ])],
        capture_output=True, text=True, check=True,
    )
    lines = result.stdout.strip().split("\n")
    fw_prefix, version = lines

    if not fw_prefix:
        raise RuntimeError(
            "Python was not built as a framework. "
            "VoxBridge requires a framework build of Python (e.g. Homebrew python)."
        )

    framework_src = os.path.join(fw_prefix, "Python.framework")
    dylib_path = os.path.join(framework_src, "Versions", version, "Python")
    if not os.path.exists(dylib_path):
        raise RuntimeError(f"Python dylib not found: {dylib_path}")

    # Get the dylib's install name (what extension modules reference)
    otool_result = subprocess.run(
        ["otool", "-D", dylib_path],
        capture_output=True, text=True, check=True,
    )
    # otool -D output: first line is filename, second line is install_name
    install_name = otool_result.stdout.strip().split("\n")[-1].strip()

    return {
        "framework_src": framework_src,
        "dylib_path": dylib_path,
        "dylib_install_name": install_name,
        "version": version,
        "base_python": base_python,
    }


# ---------------------------------------------------------------------------
# Compile native Mach-O launcher (resolves paths relative to itself)
# ---------------------------------------------------------------------------
_LAUNCHER_C_TEMPLATE = r"""
/*
 * VoxBridge launcher – self-contained .app bundle.
 *
 * Resolves all paths relative to the executable's location using
 * _NSGetExecutablePath(). No absolute paths are baked in (except
 * the Python version string).
 *
 * Layout:
 *   Contents/MacOS/VoxBridge          <- this binary
 *   Contents/Resources/               <- Python source, config, prompts
 *   Contents/Resources/venv/          <- Python venv (site-packages)
 *   Contents/Frameworks/Python.framework/  <- Python runtime
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <dlfcn.h>
#include <wchar.h>
#include <mach-o/dyld.h>
#include <limits.h>

typedef int  (*fn_Py_Main)(int, wchar_t **);
typedef void (*fn_Py_SetProgramName)(const wchar_t *);

int main(int argc, char *argv[]) {
    /* --- Resolve Contents/ directory from executable path --- */
    char exe_buf[PATH_MAX];
    uint32_t buf_size = sizeof(exe_buf);
    if (_NSGetExecutablePath(exe_buf, &buf_size) != 0) {
        fprintf(stderr, "VoxBridge: _NSGetExecutablePath failed\n");
        return 1;
    }

    char contents[PATH_MAX];
    if (!realpath(exe_buf, contents)) {
        fprintf(stderr, "VoxBridge: realpath failed\n");
        return 1;
    }

    /* contents = ".../VoxBridge.app/Contents/MacOS/VoxBridge"
     * Strip "/MacOS/VoxBridge" to get Contents/ */
    char *slash;
    slash = strrchr(contents, '/'); if (slash) *slash = '\0';
    slash = strrchr(contents, '/'); if (slash) *slash = '\0';

    /* --- Build paths (only Python version is baked in) --- */
    const char *pyver = "@@PYTHON_VERSION@@";

    char runtime_dir[PATH_MAX];
    snprintf(runtime_dir, sizeof(runtime_dir),
             "%s/Resources", contents);

    char python_dylib[PATH_MAX];
    snprintf(python_dylib, sizeof(python_dylib),
             "%s/Frameworks/Python.framework/Versions/%s/Python",
             contents, pyver);

    char python_home[PATH_MAX];
    snprintf(python_home, sizeof(python_home),
             "%s/Frameworks/Python.framework/Versions/%s",
             contents, pyver);

    char site_packages[PATH_MAX];
    snprintf(site_packages, sizeof(site_packages),
             "%s/Resources/venv/lib/python%s/site-packages",
             contents, pyver);

    char venv_python[PATH_MAX];
    snprintf(venv_python, sizeof(venv_python),
             "%s/Resources/venv/bin/python", contents);

    /* Log file: ~/Library/Logs/VoxBridge.log (resolved dynamically) */
    char log_file[PATH_MAX];
    const char *home = getenv("HOME");
    if (home) {
        snprintf(log_file, sizeof(log_file),
                 "%s/Library/Logs/VoxBridge.log", home);
    } else {
        snprintf(log_file, sizeof(log_file), "/tmp/VoxBridge.log");
    }

    /* --- Redirect stdout / stderr to log file --- */
    int fd = open(log_file, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd >= 0) {
        dup2(fd, STDOUT_FILENO);
        dup2(fd, STDERR_FILENO);
        close(fd);
    }
    /* stdin -> /dev/null (no terminal when launched by LaunchServices) */
    int devnull = open("/dev/null", O_RDONLY);
    if (devnull >= 0) { dup2(devnull, STDIN_FILENO); close(devnull); }

    /* --- Configure Python environment --- */
    setenv("PYTHONUNBUFFERED", "1", 1);
    setenv("PYTHONHOME", python_home, 1);

    char pythonpath[8192];
    snprintf(pythonpath, sizeof(pythonpath), "%s:%s",
             runtime_dir, site_packages);
    setenv("PYTHONPATH", pythonpath, 1);

    chdir(runtime_dir);

    /* --- Load Python shared library --- */
    void *handle = dlopen(python_dylib, RTLD_NOW | RTLD_GLOBAL);
    if (!handle) {
        fprintf(stderr, "VoxBridge: cannot load Python: %s\n", dlerror());
        return 1;
    }

    fn_Py_SetProgramName setProgramName =
        (fn_Py_SetProgramName)dlsym(handle, "Py_SetProgramName");
    fn_Py_Main pyMain =
        (fn_Py_Main)dlsym(handle, "Py_Main");

    if (!pyMain) {
        fprintf(stderr, "VoxBridge: Py_Main symbol not found\n");
        return 1;
    }

    /* Point Python at the venv binary so pyvenv.cfg is found */
    if (setProgramName) {
        wchar_t w_prog[PATH_MAX];
        mbstowcs(w_prog, venv_python, PATH_MAX);
        setProgramName(w_prog);
    }

    /* --- Run: python -m voxbridge --preload --- */
    wchar_t *py_argv[] = {
        L"voxbridge",
        L"-m", L"voxbridge",
        L"--preload",
    };
    return pyMain(4, py_argv);
}
"""


def _compile_launcher(output_path: str, python_version: str) -> None:
    """Compile a self-contained Mach-O launcher (only Python version baked in)."""
    src = _LAUNCHER_C_TEMPLATE.replace("@@PYTHON_VERSION@@", python_version)

    with tempfile.NamedTemporaryFile(suffix=".c", mode="w", delete=False) as f:
        f.write(src)
        c_path = f.name
    try:
        arch = platform.machine()  # "arm64" or "x86_64"
        subprocess.run(
            [
                "clang", "-arch", arch, "-O2",
                "-Wl,-rpath,@executable_path/../Frameworks",
                "-o", output_path, c_path,
            ],
            check=True,
        )
    finally:
        os.unlink(c_path)


# ---------------------------------------------------------------------------
# Fix dylib references for portability
# ---------------------------------------------------------------------------
def _fix_dylib_paths(
    app_contents: str, python_version: str, old_install_name: str,
) -> None:
    """Rewrite dylib install names so the bundle doesn't reference host paths."""
    new_install_name = (
        f"@rpath/Python.framework/Versions/{python_version}/Python"
    )
    rpath = "@executable_path/../Frameworks"

    bundled_dylib = os.path.join(
        app_contents, "Frameworks", "Python.framework",
        "Versions", python_version, "Python",
    )
    bundled_dylib_real = os.path.realpath(bundled_dylib)

    # Fix the Python dylib's own install name
    subprocess.run(
        ["install_name_tool", "-id", new_install_name, bundled_dylib],
        check=True,
    )

    # Fix all .so and .dylib files that reference the old Python dylib
    for root, _dirs, files in os.walk(app_contents):
        for fname in files:
            if not fname.endswith((".so", ".dylib")):
                continue
            fpath = os.path.join(root, fname)
            # Skip symlinks and the Python dylib itself
            if os.path.islink(fpath):
                continue
            if os.path.realpath(fpath) == bundled_dylib_real:
                continue
            # Update the Python dylib reference
            subprocess.run(
                ["install_name_tool", "-change",
                 old_install_name, new_install_name, fpath],
                capture_output=True, check=False,
            )
            # Add rpath so @rpath references can resolve
            subprocess.run(
                ["install_name_tool", "-add_rpath", rpath, fpath],
                capture_output=True, check=False,
            )

    print(f"  Dylib paths: {old_install_name} -> {new_install_name}")


# ---------------------------------------------------------------------------
# Build .app bundle
# ---------------------------------------------------------------------------
def build_app() -> str:
    """Create a self-contained VoxBridge.app bundle. Returns path to .app."""
    if os.path.exists(APP_PATH):
        shutil.rmtree(APP_PATH)

    contents = os.path.join(APP_PATH, "Contents")
    macos_dir = os.path.join(contents, "MacOS")
    resources = os.path.join(contents, "Resources")
    frameworks = os.path.join(contents, "Frameworks")
    os.makedirs(macos_dir)
    os.makedirs(resources)
    os.makedirs(frameworks)

    # --- Detect Python info ---
    py_info = _detect_python_info()
    python_version = py_info["version"]
    print(f"  Python version: {python_version}")
    print(f"  Python framework: {py_info['framework_src']}")

    # --- Copy Python.framework ---
    print(f"  Copying Python.framework ...")
    fw_version_src = os.path.join(
        py_info["framework_src"], "Versions", python_version,
    )
    fw_dest = os.path.join(frameworks, "Python.framework")
    fw_version_dest = os.path.join(fw_dest, "Versions", python_version)
    shutil.copytree(fw_version_src, fw_version_dest, symlinks=True)
    # Create standard framework symlinks
    os.symlink(python_version, os.path.join(fw_dest, "Versions", "Current"))
    os.symlink(
        f"Versions/Current/Python", os.path.join(fw_dest, "Python"),
    )
    print(f"  Python.framework -> {fw_dest}")

    # --- Copy source code, config, prompts ---
    print(f"  Copying source code ...")
    shutil.copytree(
        os.path.join(PROJECT_DIR, "voxbridge"),
        os.path.join(resources, "voxbridge"),
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy2(
        os.path.join(PROJECT_DIR, "config.yaml"),
        os.path.join(resources, "config.yaml"),
    )
    shutil.copytree(
        os.path.join(PROJECT_DIR, "prompts"),
        os.path.join(resources, "prompts"),
    )

    # --- Create venv and install dependencies ---
    venv_dir = os.path.join(resources, "venv")
    print(f"  Creating venv: {venv_dir}")
    subprocess.run(
        [py_info["base_python"], "-m", "venv", venv_dir],
        check=True,
    )

    pip = os.path.join(venv_dir, "bin", "pip")
    req = os.path.join(PROJECT_DIR, "requirements.txt")
    print(f"  Installing dependencies (this may take a minute) ...")
    subprocess.run([pip, "install", "-q", "-r", req], check=True)
    print(f"  Dependencies installed.")

    # --- Fix dylib paths for portability ---
    _fix_dylib_paths(contents, python_version, py_info["dylib_install_name"])

    # --- Icon ---
    icon_path = os.path.join(resources, "icon.icns")
    generate_icon(icon_path)

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

    # --- Compile Mach-O launcher ---
    exec_path = os.path.join(macos_dir, APP_NAME)
    _compile_launcher(exec_path, python_version)
    print(f"  Executable: {exec_path} (self-contained Mach-O)")

    # --- Code signing (ad-hoc) ---
    # Sign individual Mach-O binaries first, then framework, then app
    print(f"  Signing binaries ...")
    for root, _dirs, files in os.walk(contents):
        for fname in files:
            if fname.endswith((".so", ".dylib")):
                fpath = os.path.join(root, fname)
                if os.path.islink(fpath):
                    continue
                subprocess.run(
                    ["codesign", "--force", "--sign", "-", fpath],
                    capture_output=True, check=False,
                )
    # Sign the framework bundle
    fw_path = os.path.join(frameworks, "Python.framework")
    subprocess.run(
        ["codesign", "--force", "--sign", "-", fw_path],
        capture_output=True, check=False,
    )
    # Sign the app bundle
    subprocess.run(
        ["codesign", "--force", "--sign", "-", APP_PATH],
        check=True,
    )
    print(f"  Signed: ad-hoc")

    # --- Register with LaunchServices ---
    ls_register = (
        "/System/Library/Frameworks/CoreServices.framework/"
        "Frameworks/LaunchServices.framework/Support/lsregister"
    )
    subprocess.run([ls_register, "-f", APP_PATH], check=False)
    print(f"  Registered with LaunchServices")

    log_file = "~/Library/Logs/VoxBridge.log"
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
