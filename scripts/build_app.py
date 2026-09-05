#!/usr/bin/env python3
"""
Tinix-Facebook-Hunter — App Build & Version Management Script
- Bumps semantic version in core/version.py (patch by default)
- Verifies and updates START.bat launcher
- Creates / updates Windows Desktop shortcut pointing to START.bat
- Validates JS and Python syntax
"""

import argparse
import os
import re
import subprocess
import sys

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(BASE_DIR, "core", "version.py")
SHORTCUT_SCRIPT = os.path.join(BASE_DIR, "utils", "create_shortcut.py")


def read_current_version() -> str:
    if not os.path.exists(VERSION_FILE):
        return "1.0.0"
    with open(VERSION_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', content)
    return match.group(1) if match else "1.0.0"


def bump_semver(version: str, bump_type: str = "patch") -> str:
    parts = version.split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return version

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    else:  # patch
        return f"{major}.{minor}.{patch + 1}"


def write_version(new_version: str):
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(f'APP_VERSION = "{new_version}"\n')


def update_shortcut() -> bool:
    try:
        sys.path.insert(0, BASE_DIR)
        from utils.create_shortcut import create_desktop_shortcut
        return create_desktop_shortcut()
    except Exception as e:
        print(f"⚠️ Warning: Could not update shortcut: {e}")
        return False


def validate_syntax() -> bool:
    print("🔍 Checking code syntax...")
    # Check JS
    js_path = os.path.join(BASE_DIR, "web", "static", "app.js")
    if os.path.exists(js_path):
        res = subprocess.run(["node", "--check", js_path], capture_output=True, text=True)
        if res.returncode != 0:
            print(f"❌ Syntax error in app.js:\n{res.stderr}")
            return False

    # Check key python files
    py_files = [
        os.path.join(BASE_DIR, "main.py"),
        os.path.join(BASE_DIR, "start_webui.py"),
        os.path.join(BASE_DIR, "core", "version.py"),
        os.path.join(BASE_DIR, "web", "app.py"),
    ]
    for py_file in py_files:
        if os.path.exists(py_file):
            res = subprocess.run([sys.executable, "-m", "py_compile", py_file], capture_output=True, text=True)
            if res.returncode != 0:
                print(f"❌ Syntax error in {os.path.basename(py_file)}:\n{res.stderr}")
                return False

    print("✅ Syntax verification passed.")
    return True


def build(bump_type: str = "patch", set_version: str = None, no_bump: bool = False):
    print("=" * 60)
    print("🚀 Tinix-Facebook-Hunter — App Builder")
    print("=" * 60)

    current_ver = read_current_version()
    new_ver = current_ver

    if set_version:
        new_ver = set_version
        write_version(new_ver)
        print(f"📌 Version updated: v{current_ver} -> v{new_ver}")
    elif not no_bump:
        new_ver = bump_semver(current_ver, bump_type)
        write_version(new_ver)
        print(f"📌 Version bumped ({bump_type}): v{current_ver} -> v{new_ver}")
    else:
        print(f"📌 Current version: v{current_ver} (no bump)")

    if not validate_syntax():
        print("❌ Build failed validation!")
        sys.exit(1)

    # Refresh desktop shortcut
    print("🖥️  Updating Desktop shortcut...")
    update_shortcut()

    print("=" * 60)
    print(f"🎉 Build complete! Tinix-Facebook-Hunter v{new_ver}")
    print(f"   Launcher : {os.path.join(BASE_DIR, 'START.bat')}")
    print(f"   App Mode : Standalone (Chrome / Edge)")
    print("=" * 60)
    return new_ver


def main():
    parser = argparse.ArgumentParser(description="Tinix App Builder & Version Bumper")
    parser.add_argument("--bump", choices=["patch", "minor", "major"], default="patch", help="Version bump type (default: patch)")
    parser.add_argument("--set-version", type=str, default=None, help="Set explicit version")
    parser.add_argument("--no-bump", action="store_true", help="Do not increment version")
    args = parser.parse_args()

    build(bump_type=args.bump, set_version=args.set_version, no_bump=args.no_bump)


if __name__ == "__main__":
    main()
