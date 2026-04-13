"""
Tinix Facebook Down — Progress Panel
Shows download progress bars, statistics, and ETA.
"""

import customtkinter as ctk
from typing import Optional


class ProgressPanel(ctk.CTkFrame):
    """
    Progress panel showing:
    - Overall progress bar (posts completed)
    - Current status label
    - Statistics (files downloaded, size, time)
    - ETA
    """

    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            fg_color="#FFFFFF",
            corner_radius=12,
            border_width=1,
            border_color="#E2E8F0",
            **kwargs,
        )

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the progress panel UI."""
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=12)

        # Row 1: Status label + percentage
        row1 = ctk.CTkFrame(inner, fg_color="transparent")
        row1.pack(fill="x")

        self._status_label = ctk.CTkLabel(
            row1,
            text="Sẵn sàng",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#1E293B",
        )
        self._status_label.pack(side="left")

        self._percent_label = ctk.CTkLabel(
            row1,
            text="0%",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#2563EB",
        )
        self._percent_label.pack(side="right")

        # Row 2: Progress bar
        self._progress_bar = ctk.CTkProgressBar(
            inner,
            height=12,
            corner_radius=6,
            fg_color="#E2E8F0",
            progress_color="#2563EB",
        )
        self._progress_bar.pack(fill="x", pady=(6, 8))
        self._progress_bar.set(0)

        # Row 3: Statistics
        stats_frame = ctk.CTkFrame(inner, fg_color="#F8FAFC", corner_radius=8)
        stats_frame.pack(fill="x")

        stats_inner = ctk.CTkFrame(stats_frame, fg_color="transparent")
        stats_inner.pack(fill="x", padx=12, pady=8)

        # Left stats: Posts
        left_stats = ctk.CTkFrame(stats_inner, fg_color="transparent")
        left_stats.pack(side="left")

        self._posts_label = ctk.CTkLabel(
            left_stats,
            text="📝 Posts: 0/0",
            font=ctk.CTkFont(size=12),
            text_color="#475569",
        )
        self._posts_label.pack(anchor="w")

        self._media_label = ctk.CTkLabel(
            left_stats,
            text="📷 Media: 0/0",
            font=ctk.CTkFont(size=12),
            text_color="#475569",
        )
        self._media_label.pack(anchor="w")

        # Center stats: Success/Failed
        center_stats = ctk.CTkFrame(stats_inner, fg_color="transparent")
        center_stats.pack(side="left", padx=40)

        self._success_label = ctk.CTkLabel(
            center_stats,
            text="✅ Thành công: 0",
            font=ctk.CTkFont(size=12),
            text_color="#16A34A",
        )
        self._success_label.pack(anchor="w")

        self._failed_label = ctk.CTkLabel(
            center_stats,
            text="❌ Thất bại: 0",
            font=ctk.CTkFont(size=12),
            text_color="#DC2626",
        )
        self._failed_label.pack(anchor="w")

        # Right stats: Time
        right_stats = ctk.CTkFrame(stats_inner, fg_color="transparent")
        right_stats.pack(side="right")

        self._time_label = ctk.CTkLabel(
            right_stats,
            text="⏱ Thời gian: 00:00",
            font=ctk.CTkFont(size=12),
            text_color="#475569",
        )
        self._time_label.pack(anchor="e")

        self._eta_label = ctk.CTkLabel(
            right_stats,
            text="⏳ ETA: --:--",
            font=ctk.CTkFont(size=12),
            text_color="#475569",
        )
        self._eta_label.pack(anchor="e")

    # --- Public API ---

    def update_progress(
        self,
        completed: int = 0,
        total: int = 0,
        success: int = 0,
        failed: int = 0,
        media_downloaded: int = 0,
        media_total: int = 0,
        elapsed_sec: float = 0,
        eta_sec: float = 0,
        status_text: Optional[str] = None,
        total_bytes: int = 0,
    ) -> None:
        """Update all progress indicators."""
        # Progress bar
        fraction = completed / total if total > 0 else 0
        self._progress_bar.set(fraction)

        # Percentage
        percent = int(fraction * 100)
        self._percent_label.configure(text=f"{percent}%")

        # Status
        if status_text:
            self._status_label.configure(text=status_text)
        elif total > 0:
            self._status_label.configure(text=f"Đang xử lý... ({completed}/{total})")
        else:
            self._status_label.configure(text="Sẵn sàng")

        # Stats
        self._posts_label.configure(text=f"📝 Posts: {completed}/{total}")
        self._media_label.configure(
            text=f"📷 Media: {media_downloaded}/{media_total}"
            + (f" ({self._format_size(total_bytes)})" if total_bytes > 0 else "")
        )
        self._success_label.configure(text=f"✅ Thành công: {success}")
        self._failed_label.configure(text=f"❌ Thất bại: {failed}")

        # Time
        self._time_label.configure(text=f"⏱ Thời gian: {self._format_time(elapsed_sec)}")
        if eta_sec > 0:
            self._eta_label.configure(text=f"⏳ ETA: ~{self._format_time(eta_sec)}")
        else:
            self._eta_label.configure(text="⏳ ETA: --:--")

    def set_complete(self, success: bool = True) -> None:
        """Set progress to complete state."""
        if success:
            self._status_label.configure(text="✅ Hoàn thành!", text_color="#16A34A")
            self._progress_bar.configure(progress_color="#16A34A")
        else:
            self._status_label.configure(text="⚠️ Hoàn thành với lỗi", text_color="#D97706")
            self._progress_bar.configure(progress_color="#D97706")
        self._eta_label.configure(text="⏳ ETA: --:--")

    def set_stopped(self) -> None:
        """Set progress to stopped state."""
        self._status_label.configure(text="⏹ Đã dừng", text_color="#DC2626")
        self._progress_bar.configure(progress_color="#94A3B8")
        self._eta_label.configure(text="⏳ ETA: --:--")

    def reset(self) -> None:
        """Reset all progress indicators."""
        self._progress_bar.set(0)
        self._progress_bar.configure(progress_color="#2563EB")
        self._percent_label.configure(text="0%")
        self._status_label.configure(text="Sẵn sàng", text_color="#1E293B")
        self._posts_label.configure(text="📝 Posts: 0/0")
        self._media_label.configure(text="📷 Media: 0/0")
        self._success_label.configure(text="✅ Thành công: 0")
        self._failed_label.configure(text="❌ Thất bại: 0")
        self._time_label.configure(text="⏱ Thời gian: 00:00")
        self._eta_label.configure(text="⏳ ETA: --:--")

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds to MM:SS or HH:MM:SS."""
        seconds = int(seconds)
        if seconds < 3600:
            return f"{seconds // 60:02d}:{seconds % 60:02d}"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format file size."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
