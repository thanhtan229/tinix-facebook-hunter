"""
Tinix-Facebook-Hunter — Main Entry Point
Launches the WebUI Studio server and opens the browser.
"""

import sys
import os

# Ensure the project root is in the Python path
if getattr(sys, 'frozen', False):
    _base_dir = os.path.dirname(sys.executable)
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))

if _base_dir not in sys.path:
    sys.path.insert(0, _base_dir)

from start_webui import main

if __name__ == "__main__":
    main()
