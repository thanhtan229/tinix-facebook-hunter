"""
Tinix Facebook Down — Main Application Window
Assembles all GUI panels with a tabbed interface (Tải Media + Quét Page).
"""

import os
import subprocess
import sys

import customtkinter as ctk

from gui.input_panel import InputPanel
from gui.control_panel import ControlPanel
from gui.progress_panel import ProgressPanel
from gui.console_panel import ConsolePanel
from gui.settings_dialog import SettingsDialog
from gui.history_dialog import HistoryDialog
from gui.scrape_tab import ScrapeTab
from gui.dashboard_tab import DashboardTab
from gui.social_post_tab import SocialPostTab
from core.downloader import DownloadOrchestrator, DownloadStats
from utils import config, logger
from utils.history import HistoryEntry, add_entry


APP_NAME = "Tinix Facebook Down"
APP_VERSION = "1.1.1"


class MainApp(ctk.CTk):
    """
    Main application window.
    Uses CTkTabview with two tabs:
    - Tab 1: "Tải Media" (original download functionality)
    - Tab 2: "Quét Page" (new scrape-to-Excel functionality)
    """

    def __init__(self):
        super().__init__()

        # Load config
        self._cfg = config.load_config()

        # Window setup
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.minsize(800, 700)
        self.configure(fg_color="#F5F5F7")

        # Get screen dimensions and clamp window size
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        # Use fixed default size, ignore saved size to avoid DPI issues
        width = min(980, screen_w - 100)
        height = min(800, screen_h - 100)

        # Center on screen
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

        # Set icon if available
        icon_path = self._get_asset_path("icon.ico")
        if icon_path and os.path.exists(icon_path):
            self.iconbitmap(icon_path)

        # Initialize orchestrator (for download tab)
        self._orchestrator = DownloadOrchestrator()
        self._orchestrator.set_callbacks(
            on_stats_update=self._on_stats_update,
            on_all_complete=self._on_all_complete,
        )

        # Build UI
        self._setup_ui()

        # Connect logger to console (download tab console)
        logger.setup_logger()
        logger.set_gui_callback(self._on_log_message)

        # Save window size on close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Welcome message
        logger.info(f"🚀 {APP_NAME} v{APP_VERSION} — Sẵn sàng!")
        logger.info(f"Thư mục lưu mặc định: {self._cfg.get('output_dir', 'N/A')}")

        # V15: Check for missed posts 2s after startup (non-blocking)
        self.after(2000, self._check_missed_posts)

    def _setup_ui(self) -> None:
        """Build the main application layout with tabs."""
        # App title bar
        title_frame = ctk.CTkFrame(self, fg_color="transparent")
        title_frame.pack(fill="x", padx=20, pady=(16, 8))

        ctk.CTkLabel(
            title_frame,
            text=f"🔽 {APP_NAME}",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#1E293B",
        ).pack(side="left")

        ctk.CTkLabel(
            title_frame,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=12),
            text_color="#94A3B8",
        ).pack(side="left", padx=8, pady=(6, 0))

        # Settings & History buttons in title bar (shared across tabs)
        btn_frame = ctk.CTkFrame(title_frame, fg_color="transparent")
        btn_frame.pack(side="right")

        ctk.CTkButton(
            btn_frame,
            text="📋",
            width=40, height=40,
            font=ctk.CTkFont(size=18),
            fg_color="#F1F5F9", text_color="#475569",
            hover_color="#E2E8F0", corner_radius=10,
            command=self._on_history,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_frame,
            text="⚙",
            width=40, height=40,
            font=ctk.CTkFont(size=18),
            fg_color="#F1F5F9", text_color="#475569",
            hover_color="#E2E8F0", corner_radius=10,
            command=self._on_settings,
        ).pack(side="right")

        # ===== Tabview =====
        self._tabview = ctk.CTkTabview(
            self,
            fg_color="#F5F5F7",
            segmented_button_fg_color="#1E293B",
            segmented_button_selected_color="#2563EB",
            segmented_button_selected_hover_color="#1D4ED8",
            segmented_button_unselected_color="#1E293B",
            segmented_button_unselected_hover_color="#334155",
            corner_radius=12,
            border_width=0,
        )
        self._tabview.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        # Configure tab font
        self._tabview._segmented_button.configure(
            font=ctk.CTkFont(size=14, weight="bold"),
        )

        # Tab 1: Tải Media
        tab_download = self._tabview.add("  📥  Tải Media  ")
        self._setup_download_tab(tab_download)

        # Tab 2: Quét Page
        tab_scrape = self._tabview.add("  📊  Quét Page  ")
        self._setup_scrape_tab(tab_scrape)

        # Tab 3: Dashboard
        tab_dashboard = self._tabview.add("  📈  Dashboard  ")
        self._setup_dashboard_tab(tab_dashboard)

        # Tab 4: Social Post
        tab_social = self._tabview.add("  📤  Social Post  ")
        self._setup_social_post_tab(tab_social)

        # Tab 5: Video Post
        tab_video = self._tabview.add("  🎬  Video Post  ")
        self._setup_video_post_tab(tab_video)

        # Default to first tab
        self._tabview.set("  📥  Tải Media  ")

    def _setup_download_tab(self, parent) -> None:
        """Build the download tab (original functionality)."""
        # Input Panel
        self._input_panel = InputPanel(parent)
        self._input_panel.pack(fill="x", padx=4, pady=(4, 8))

        # Control Panel
        self._control_panel = ControlPanel(
            parent,
            on_run=self._on_run,
            on_pause=self._on_pause,
            on_stop=self._on_stop,
            on_reset=self._on_reset,
            on_settings=self._on_settings,
            on_history=self._on_history,
            on_open_folder=self._on_open_folder,
        )
        self._control_panel.pack(fill="x", padx=4, pady=(0, 8))

        # Progress Panel
        self._progress_panel = ProgressPanel(parent)
        self._progress_panel.pack(fill="x", padx=4, pady=(0, 8))

        # Console Panel (takes remaining space)
        self._console_panel = ConsolePanel(parent)
        self._console_panel.pack(fill="both", expand=True, padx=4, pady=(0, 4))

    def _setup_scrape_tab(self, parent) -> None:
        """Build the scrape tab (new functionality)."""
        self._scrape_tab = ScrapeTab(parent)
        self._scrape_tab.pack(fill="both", expand=True, padx=4, pady=4)

    def _setup_dashboard_tab(self, parent) -> None:
        """Build the dashboard tab."""
        self._dashboard_tab = DashboardTab(
            parent,
            on_send_to_download=self._send_urls_to_download,
        )
        self._dashboard_tab.pack(fill="both", expand=True, padx=4, pady=4)

    def _setup_social_post_tab(self, parent) -> None:
        """Build the social post tab."""
        self._social_post_tab = SocialPostTab(parent)
        self._social_post_tab.pack(fill="both", expand=True, padx=4, pady=4)

    def _setup_video_post_tab(self, parent) -> None:
        """Build the video post tab."""
        from gui.video_post_tab import VideoPostTab
        self._video_post_tab = VideoPostTab(parent)
        self._video_post_tab.pack(fill="both", expand=True, padx=4, pady=4)

    def _send_urls_to_download(self, urls: list) -> None:
        """Receive URLs from Dashboard and send to Download tab."""
        try:
            self._tabview.set("  📥  Tải Media  ")
            self._input_panel.clear()
            self._input_panel._url_textbox.insert("1.0", "\n".join(urls))
            logger.info(f"📥 Đã gửi {len(urls)} URL sang tab Tải Media")
        except Exception as e:
            logger.error(f"Lỗi gửi URLs: {str(e)[:100]}")

    # --- Download Tab: Action Handlers ---

    def _on_run(self) -> None:
        """Handle Run button click."""
        urls = self._input_panel.get_urls()
        output_dir = self._input_panel.get_output_dir()

        if not urls.strip():
            logger.error("Vui lòng nhập ít nhất 1 URL Facebook!")
            return

        if not output_dir.strip():
            logger.error("Vui lòng chọn thư mục lưu!")
            return

        # Get cookies from config (saved via Settings)
        cookies = config.get("saved_cookies", "")
        if not cookies.strip():
            logger.error("Chưa có cookies! Vui lòng vào ⚙ Cài đặt để nhập cookies.")
            return

        # Update output dir in config
        config.set_value("output_dir", output_dir)

        # Disable inputs
        self._input_panel.set_state("disabled")
        self._control_panel.set_running()
        self._progress_panel.reset()
        self._console_panel.clear()

        # Store URLs for history
        self._current_urls = urls.strip().splitlines()

        # Start download
        max_threads = self._cfg.get("max_threads", 1)
        self._orchestrator.start(urls, cookies, output_dir, max_threads)

    def _on_pause(self, should_pause: bool) -> None:
        """Handle Pause/Resume button click."""
        if should_pause:
            self._orchestrator.pause()
            self._control_panel.set_paused()
        else:
            self._orchestrator.resume()
            self._control_panel.set_resumed()

    def _on_stop(self) -> None:
        """Handle Stop button click."""
        self._orchestrator.stop()
        self._control_panel.set_idle()
        self._input_panel.set_state("normal")
        self._progress_panel.set_stopped()

    def _on_reset(self) -> None:
        """Handle Reset button click."""
        self._orchestrator.reset()
        self._input_panel.clear()
        self._progress_panel.reset()
        self._console_panel.clear()
        self._control_panel.set_idle()
        self._input_panel.set_state("normal")
        logger.info("🔄 Đã reset tất cả")

    def _on_settings(self) -> None:
        """Open settings dialog."""
        SettingsDialog(self, on_save=self._on_settings_saved)

    def _on_history(self) -> None:
        """Open history dialog."""
        HistoryDialog(self)

    def _on_settings_saved(self, new_cfg: dict) -> None:
        """Handle settings save."""
        self._cfg = new_cfg
        logger.info("⚙ Cài đặt đã được lưu")

    def _on_open_folder(self) -> None:
        """Open the output directory in file explorer."""
        output_dir = self._input_panel.get_output_dir()
        if output_dir and os.path.exists(output_dir):
            try:
                os.startfile(output_dir)
            except Exception:
                logger.error("Không thể mở thư mục")
        else:
            logger.warning("Thư mục lưu chưa tồn tại")

    # --- Callbacks from Orchestrator (called from background threads) ---

    def _on_log_message(self, level: str, message: str) -> None:
        """
        Receive log messages from the logger.
        Thread-safe: uses after() to update GUI.
        """
        self.after(0, self._console_panel.append_log, level, message)

    def _on_stats_update(self, stats: DownloadStats) -> None:
        """
        Receive stats updates from the orchestrator.
        Thread-safe: uses after() to update GUI.
        """
        self.after(0, self._update_progress_from_stats, stats)

    def _on_all_complete(self, success: bool, message: str) -> None:
        """
        Receive completion signal from the orchestrator.
        Thread-safe: uses after() to update GUI.
        """
        self.after(0, self._handle_completion, success, message)

    # --- GUI Update Methods (must run on main thread) ---

    def _update_progress_from_stats(self, stats: DownloadStats) -> None:
        """Update progress panel from stats (main thread)."""
        self._progress_panel.update_progress(
            completed=stats.completed_posts,
            total=stats.total_posts,
            success=stats.success_posts,
            failed=stats.failed_posts,
            media_downloaded=stats.downloaded_media,
            media_total=stats.total_media,
            elapsed_sec=stats.elapsed_seconds,
            eta_sec=stats.eta_seconds,
            total_bytes=stats.total_bytes,
        )

    def _handle_completion(self, success: bool, message: str) -> None:
        """Handle download completion (main thread)."""
        self._control_panel.set_idle()
        self._input_panel.set_state("normal")

        stats = self._orchestrator.stats
        has_failures = stats.failed_posts > 0
        self._progress_panel.set_complete(success=not has_failures)

        # Save to history
        urls = getattr(self, '_current_urls', [])
        entry = HistoryEntry.create(
            urls=urls,
            success=stats.success_posts,
            failed=stats.failed_posts,
            output_dir=self._input_panel.get_output_dir(),
        )
        add_entry(entry)

        # Auto-open folder if enabled
        if self._cfg.get("auto_open_folder", False) and success:
            output_dir = self._input_panel.get_output_dir()
            if os.path.exists(output_dir):
                try:
                    if sys.platform == "win32":
                        os.startfile(output_dir)
                except Exception:
                    pass

    # --- Utilities ---

    def _check_missed_posts(self) -> None:
        """V15: Check for App-mode posts that were missed while app was closed."""
        try:
            from core.db_storage import get_db_path, get_missed_app_posts
            from utils import config as _cfg_mod
            db_path = get_db_path(_cfg_mod.get("scraper_db_path", ""))
            missed = get_missed_app_posts(db_path)
            if missed:
                from gui.missed_post_dialog import MissedPostDialog
                MissedPostDialog(
                    self,
                    missed=missed,
                    on_execute_now=self._execute_missed_posts,
                )
        except Exception as e:
            logger.debug(f"_check_missed_posts error: {str(e)[:100]}")

    def _execute_missed_posts(self, records: list) -> None:
        """V15: Hand missed records to the Social Post tab's execute handler."""
        try:
            self._tabview.set("  📤  Social Post  ")
            self._social_post_tab._execute_records_from_calendar(records)
        except Exception as e:
            logger.error(f"_execute_missed_posts error: {str(e)[:100]}")

    def _on_close(self) -> None:
        """Handle window close."""
        # Stop any running downloads
        if self._orchestrator.is_running:
            self._orchestrator.stop()

        self.destroy()

    @staticmethod
    def _get_asset_path(filename: str) -> str:
        """Get path to an asset file."""
        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "assets", filename)
