"""Persistence helpers for application data."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import AppSettings, PendingWorklog, TimerState


APP_DIR_NAME = "JiraStopWatch"
STATE_FILE = "state.json"
WORKLOG_FILE = "pending_worklogs.json"
SETTINGS_FILE = "settings.json"


def _get_base_directory() -> Path:
    """Return a suitable directory for storing application data."""
    if os.name == "nt":
        root = os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming"
        return Path(root) / APP_DIR_NAME
    return Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_DIR_NAME


def ensure_storage_directory() -> Path:
    directory = _get_base_directory()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def load_state() -> list[TimerState]:
    directory = ensure_storage_directory()
    path = directory / STATE_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    timers = []
    for payload in data:
        try:
            timers.append(TimerState.deserialize(payload))
        except Exception:
            continue
    return timers


def save_state(timers: list[TimerState]) -> None:
    directory = ensure_storage_directory()
    path = directory / STATE_FILE
    payload = [timer.serialize() for timer in timers]
    path.write_text(json.dumps(payload, indent=2))


def load_settings() -> AppSettings:
    directory = ensure_storage_directory()
    path = directory / SETTINGS_FILE
    if not path.exists():
        return AppSettings()
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return AppSettings()
    return AppSettings.deserialize(data)


def save_settings(settings: AppSettings) -> None:
    directory = ensure_storage_directory()
    path = directory / SETTINGS_FILE
    path.write_text(json.dumps(settings.serialize(), indent=2))


def load_pending_worklogs() -> list[PendingWorklog]:
    directory = ensure_storage_directory()
    path = directory / WORKLOG_FILE
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    worklogs: list[PendingWorklog] = []
    for payload in data:
        try:
            worklogs.append(PendingWorklog.deserialize(payload))
        except Exception:
            continue
    return worklogs


def save_pending_worklogs(worklogs: list[PendingWorklog]) -> None:
    directory = ensure_storage_directory()
    path = directory / WORKLOG_FILE
    payload = [worklog.serialize() for worklog in worklogs]
    path.write_text(json.dumps(payload, indent=2))


def reset_storage() -> None:
    directory = ensure_storage_directory()
    for filename in (STATE_FILE, WORKLOG_FILE, SETTINGS_FILE):
        path = directory / filename
        if path.exists():
            path.unlink()
