"""Application domain models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TimerState:
    """State persisted for a timer slot."""

    issue_key: str = ""
    description: str = ""
    seconds: int = 0
    running: bool = False
    last_started: Optional[float] = None
    comment: str = ""

    def serialize(self) -> dict:
        return {
            "issue_key": self.issue_key,
            "description": self.description,
            "seconds": self.seconds,
            "running": self.running,
            "last_started": self.last_started,
            "comment": self.comment,
        }

    @classmethod
    def deserialize(cls, payload: dict) -> "TimerState":
        state = cls()
        state.issue_key = payload.get("issue_key", "")
        state.description = payload.get("description", "")
        state.seconds = int(payload.get("seconds", 0))
        state.running = bool(payload.get("running", False))
        state.last_started = payload.get("last_started")
        state.comment = payload.get("comment", "")
        return state


@dataclass
class AppSettings:
    """Authentication and Jira filter configuration."""

    base_url: str = ""
    email: str = ""
    api_token: str = ""
    default_filter_id: str = ""
    filter_cache: dict[str, str] = field(default_factory=dict)
    dark_mode_enabled: bool = False

    def serialize(self) -> dict:
        return {
            "base_url": self.base_url,
            "email": self.email,
            "api_token": self.api_token,
            "default_filter_id": self.default_filter_id,
            "filter_cache": dict(self.filter_cache),
            "dark_mode_enabled": self.dark_mode_enabled,
        }

    @classmethod
    def deserialize(cls, payload: dict | None) -> "AppSettings":
        payload = payload or {}
        settings = cls()
        settings.base_url = payload.get("base_url", "")
        settings.email = payload.get("email", "")
        settings.api_token = payload.get("api_token", "")
        settings.default_filter_id = payload.get("default_filter_id", "")
        settings.filter_cache = dict(payload.get("filter_cache", {}))
        settings.dark_mode_enabled = bool(payload.get("dark_mode_enabled", False))
        return settings


@dataclass
class PendingWorklog:
    issue_key: str
    seconds: int
    comment: str
    created_at: datetime

    def serialize(self) -> dict:
        return {
            "issue_key": self.issue_key,
            "seconds": self.seconds,
            "comment": self.comment,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def deserialize(cls, payload: dict) -> "PendingWorklog":
        return cls(
            issue_key=payload["issue_key"],
            seconds=int(payload["seconds"]),
            comment=payload.get("comment", ""),
            created_at=datetime.fromisoformat(payload["created_at"]),
        )
