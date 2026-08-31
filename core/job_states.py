"""Canonical states shared by persistent social posting jobs."""

from enum import StrEnum


class PostJobStatus(StrEnum):
    PENDING = "Pending"
    RUNNING = "Running"
    SCHEDULED = "Scheduled"
    FAILED = "Failed"
    POSTED = "Posted"
    SKIPPED = "Skipped"
    UNSUPPORTED = "Unsupported"


POST_JOB_STATUSES = frozenset(status.value for status in PostJobStatus)
