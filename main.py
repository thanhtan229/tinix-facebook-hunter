"""
Tinix Facebook Down — Entry Point
Launches the application.
"""

import sys
import os
import threading

# Ensure the project root is in the Python path
if getattr(sys, 'frozen', False):
    # Running as compiled .exe
    _base_dir = os.path.dirname(sys.executable)
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))

if _base_dir not in sys.path:
    sys.path.insert(0, _base_dir)

import customtkinter as ctk


def main():
    """Application entry point."""
    # Set appearance mode (Light theme as requested)
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")

    # Global exception handler to prevent silent crashes
    def handle_exception(exc_type, exc_value, exc_tb):
        if exc_type == KeyboardInterrupt:
            sys.exit(0)
        import traceback
        error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(f"[FATAL ERROR]\n{error_msg}", file=sys.stderr)
        try:
            from utils import diagnostics, logger
            report_path = diagnostics.capture_exception(
                "Unhandled application exception",
                exc_value,
                exc_tb=exc_tb,
            )
            logger.error(f"Fatal error: {exc_value}")
            logger.error(f"Diagnostic report saved: {report_path}")
        except Exception:
            pass

    sys.excepthook = handle_exception

    def handle_thread_exception(args):
        handle_exception(args.exc_type, args.exc_value, args.exc_traceback)

    threading.excepthook = handle_thread_exception

    # Launch the app
    from gui.app import MainApp
    app = MainApp()
    app.mainloop()


if __name__ == "__main__":
    main()
