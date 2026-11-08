#!/usr/bin/env python3
"""
Cross-Platform Installer for KiCad PCB to G-Code Plugin.
Supports Linux, Windows, and macOS for KiCad 7, 8, 9, 10+.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

PLUGIN_FOLDER_NAME = "kicad_pcb_to_gcode"
SUPPORTED_VERSIONS = ["10.0", "9.0", "8.0", "7.0", "6.0"]


def get_default_kicad_plugin_dirs():
    """Detect available KiCad plugin directories on this machine."""
    candidates = []

    if sys.platform.startswith("linux"):
        base = Path(os.path.expanduser("~/.local/share/kicad"))
        for ver in SUPPORTED_VERSIONS:
            ver_dir = base / ver / "scripting" / "plugins"
            candidates.append((ver, ver_dir))
            cand_3rd = base / ver / "3rdparty" / "plugins"
            candidates.append((ver + " (3rdparty)", cand_3rd))
        candidates.append(("universal", Path(os.path.expanduser("~/.kicad_plugins"))))

    elif sys.platform == "win32":
        appdata = Path(os.getenv("APPDATA", os.path.expanduser("~")))
        for ver in SUPPORTED_VERSIONS:
            candidates.append((ver, appdata / "kicad" / ver / "scripting" / "plugins"))
            candidates.append((ver + " (3rdparty)", appdata / "kicad" / ver / "3rdparty" / "plugins"))
        user_docs = Path(os.path.expanduser("~/Documents"))
        for ver in SUPPORTED_VERSIONS:
            candidates.append((ver + " (Docs)", user_docs / "KiCad" / ver / "plugins"))

    elif sys.platform == "darwin":  # macOS
        app_support = Path(os.path.expanduser("~/Library/Application Support/kicad"))
        for ver in SUPPORTED_VERSIONS:
            candidates.append((ver, app_support / ver / "scripting" / "plugins"))
            candidates.append((ver + " (3rdparty)", app_support / ver / "3rdparty" / "plugins"))

    return candidates


def find_source_dir():
    """Find the source plugin directory."""
    script_dir = Path(__file__).resolve().parent
    source = script_dir / PLUGIN_FOLDER_NAME
    if source.is_dir() and (source / "__init__.py").exists():
        return source
    sys.exit(f"Error: Could not locate source plugin directory '{PLUGIN_FOLDER_NAME}' next to install.py")


def install_plugin(target_parent_dir, source_dir, use_symlink=False):
    """Install or symlink the plugin into target_parent_dir."""
    target_parent = Path(target_parent_dir)
    target_parent.mkdir(parents=True, exist_ok=True)
    destination = target_parent / PLUGIN_FOLDER_NAME

    if destination.is_symlink() or destination.is_file():
        destination.unlink()
    elif destination.is_dir():
        shutil.rmtree(destination)

    if use_symlink:
        try:
            destination.symlink_to(source_dir, target_is_directory=True)
            print(f"✓ Created symbolic link:")
            print(f"  {destination} -> {source_dir}")
            return destination
        except OSError as e:
            print(f"! Symlink failed ({e}). Falling back to file copy.")

    shutil.copytree(source_dir, destination)
    print(f"✓ Installed plugin files to:")
    print(f"  {destination}")
    return destination


def uninstall_plugin(target_parent_dir):
    """Uninstall the plugin from target_parent_dir."""
    destination = Path(target_parent_dir) / PLUGIN_FOLDER_NAME
    if destination.is_symlink() or destination.is_file():
        destination.unlink()
        print(f"✓ Removed: {destination}")
        return True
    elif destination.is_dir():
        shutil.rmtree(destination)
        print(f"✓ Removed: {destination}")
        return True
    else:
        print(f"  Not found in: {target_parent_dir}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Install KiCad PCB to G-Code Exporter Plugin")
    parser.add_argument("--symlink", action="store_true", help="Create symlink instead of copying files (useful for development)")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall the plugin from KiCad directories")
    parser.add_argument("--all", action="store_true", help="Install into all detected KiCad version folders")
    parser.add_argument("--target", type=str, help="Manually specify custom KiCad plugins directory")
    args = parser.parse_args()

    source_dir = find_source_dir()

    print("==================================================")
    print("KiCad PCB to CNC G-Code Exporter — Installer")
    print("==================================================")

    if args.target:
        target = Path(args.target)
        if args.uninstall:
            uninstall_plugin(target)
        else:
            install_plugin(target, source_dir, args.symlink)
        return

    all_candidates = get_default_kicad_plugin_dirs()
    existing_dirs = []
    for ver_name, path in all_candidates:
        if path.exists() or path.parent.exists() or path.parent.parent.exists():
            existing_dirs.append((ver_name, path))

    if not existing_dirs:
        ver_name, path = all_candidates[0]
        existing_dirs = [(ver_name, path)]

    if args.uninstall:
        print("Uninstalling plugin from detected KiCad directories...")
        for ver_name, path in existing_dirs:
            uninstall_plugin(path)
        print("Uninstall finished.")
        return

    print("Detected KiCad configuration directories:")
    for ver_name, path in existing_dirs:
        print(f"  • KiCad {ver_name}: {path}")

    if args.all:
        for ver_name, path in existing_dirs:
            print(f"\nInstalling for KiCad {ver_name}...")
            install_plugin(path, source_dir, args.symlink)
    else:
        primary = None
        for ver_name, path in existing_dirs:
            if "scripting" in str(path):
                primary = (ver_name, path)
                break
        if not primary:
            primary = existing_dirs[0]

        ver_name, target_dir = primary
        print(f"\nInstalling for primary version: KiCad {ver_name}...")
        installed_dest = install_plugin(target_dir, source_dir, args.symlink)

        for v_name, p_path in existing_dirs:
            if "3rdparty" in str(p_path) and p_path.parent.exists():
                print(f"Also linking to 3rdparty plugins for KiCad {v_name}...")
                install_plugin(p_path, source_dir, args.symlink)

    print("\n==================================================")
    print("INSTALLATION SUCCESSFUL!")
    print("==================================================")
    print("How to access in KiCad:")
    print("  1. Launch KiCad and open PCB Editor (pcbnew).")
    print("  2. If KiCad is already running, either restart it OR in the")
    print("     Scripting Console run:")
    print("         import pcbnew; pcbnew.LoadPlugins()")
    print("  3. You will see:")
    print("     • Menu Bar: 'Tools' -> 'External Plugins' -> 'Export PCB to G-Code (.nc)'")
    print("     • Top Toolbar: Click the new CNC Spindle & PCB Drill Icon!")
    print("  4. The form will open with full settings and layer selections.")
    print("==================================================")


if __name__ == "__main__":
    main()
