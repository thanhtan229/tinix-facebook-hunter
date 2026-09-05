"""
Utility to create a Windows Desktop shortcut with the custom app icon.
"""

import os
import subprocess
import sys


def create_desktop_shortcut() -> bool:
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        start_bat = os.path.join(base_dir, "START.bat")
        target_bat = start_bat if os.path.exists(start_bat) else os.path.join(base_dir, "Run.bat")
        icon_ico = os.path.join(base_dir, "assets", "icon.ico")
        desktop_dir = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")

        if not os.path.exists(desktop_dir):
            desktop_dir = os.path.expanduser("~/Desktop")

        shortcut_path = os.path.join(desktop_dir, "Tinix-Facebook-Hunter.lnk")

        # Use PowerShell script with WindowStyle = 7 (Minimized) so command window doesn't flash
        ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut('{shortcut_path}')
$s.TargetPath = '{target_bat}'
$s.WorkingDirectory = '{base_dir}'
$s.IconLocation = '{icon_ico},0'
$s.Description = 'Tinix-Facebook-Hunter (App Mode)'
$s.WindowStyle = 7
$s.Save()
"""
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"Created shortcut at: {shortcut_path}")
        return True
    except Exception as e:
        print(f"Could not create shortcut: {e}")
        return False


if __name__ == "__main__":
    create_desktop_shortcut()
