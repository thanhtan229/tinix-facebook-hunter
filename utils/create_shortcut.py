"""
Utility to create a Windows Desktop shortcut with the custom app icon.
"""

import os
import subprocess
import sys


def create_desktop_shortcut() -> bool:
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        start_vbs = os.path.join(base_dir, "START.vbs")
        start_bat = os.path.join(base_dir, "START.bat")
        if os.path.exists(start_vbs):
            target_exe = "wscript.exe"
            arguments = f'//nologo "{start_vbs}"'
        elif os.path.exists(start_bat):
            target_exe = "cmd.exe"
            arguments = f'/c "{start_bat}"'
        else:
            target_exe = "cmd.exe"
            arguments = f'/c "{os.path.join(base_dir, "Run.bat")}"'

        icon_ico = os.path.join(base_dir, "assets", "icon.ico")
        desktop_dir = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")

        if not os.path.exists(desktop_dir):
            desktop_dir = os.path.expanduser("~/Desktop")

        shortcut_path = os.path.join(desktop_dir, "Tinix-Facebook-Hunter.lnk")

        # Create shortcut targeting wscript.exe or cmd.exe with arguments to allow Pin to Taskbar
        ps_script = f"""
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut('{shortcut_path}')
$s.TargetPath = '{target_exe}'
$s.Arguments = '{arguments}'
$s.WorkingDirectory = '{base_dir}'
$s.IconLocation = '{icon_ico},0'
$s.Description = 'Tinix-Facebook-Hunter (App Mode)'
$s.WindowStyle = 1
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
