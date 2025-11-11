"""Utility helpers for the JiraStopWatch application."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 60 * SECONDS_PER_MINUTE
SECONDS_PER_DAY = 24 * SECONDS_PER_HOUR


def parse_duration(duration: str) -> int:
    """Convert a Jira style duration string (``2h 30m``) into seconds.

    Parameters
    ----------
    duration:
        Human readable duration. Supported suffixes are ``d`` (days), ``h`` (hours),
        ``m`` (minutes) and ``s`` (seconds). Multiple tokens can be combined in any
        order separated by spaces.

    Returns
    -------
    int
        The total number of seconds represented by ``duration``.

    Raises
    ------
    ValueError
        If the value cannot be parsed.
    """

    total = 0
    token = ""
    duration = duration.strip()
    if not duration:
        raise ValueError("Duration cannot be empty")

    for char in duration:
        if char.isdigit():
            token += char
            continue
        if char.isspace():
            if token:
                raise ValueError("Suffix missing for duration segment")
            continue
        if not token:
            raise ValueError(f"Missing value before suffix '{char}'")
        value = int(token)
        token = ""
        if char == "d":
            total += value * SECONDS_PER_DAY
        elif char == "h":
            total += value * SECONDS_PER_HOUR
        elif char == "m":
            total += value * SECONDS_PER_MINUTE
        elif char == "s":
            total += value
        else:
            raise ValueError(f"Unknown suffix '{char}' in duration")

    if token:
        raise ValueError("Duration segment missing suffix")

    return total


def format_duration(seconds: int) -> str:
    """Format ``seconds`` using Jira's duration representation."""
    if seconds < 0:
        raise ValueError("Duration cannot be negative")

    parts = []
    remaining = seconds

    if remaining >= SECONDS_PER_DAY:
        days, remaining = divmod(remaining, SECONDS_PER_DAY)
        parts.append(f"{days}d")
    if remaining >= SECONDS_PER_HOUR:
        hours, remaining = divmod(remaining, SECONDS_PER_HOUR)
        parts.append(f"{hours}h")
    if remaining >= SECONDS_PER_MINUTE:
        minutes, remaining = divmod(remaining, SECONDS_PER_MINUTE)
        parts.append(f"{minutes}m")
    if not parts or remaining:
        parts.append(f"{remaining}s")

    return " ".join(parts)


@dataclass
class Worklog:
    """Representation of a Jira worklog entry."""

    issue_key: str
    seconds: int
    comment: str
    started: datetime
    adjust_estimate: str
    remaining_estimate: int | None


def make_timestamp(dt: datetime | None = None) -> str:
    """Return an ISO formatted timestamp understood by Jira's API."""
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        local_timezone = datetime.now().astimezone().tzinfo
        dt = dt.replace(tzinfo=local_timezone)
    return dt.isoformat(timespec="seconds")


def make_comment_payload(comment: str) -> dict | None:
    """Return a payload compatible with Jira's Atlassian Document Format."""

    text = comment.strip()
    if not text:
        return None

    content: list[dict] = []
    lines = comment.splitlines()
    for index, line in enumerate(lines):
        if line:
            content.append({"type": "text", "text": line})
        if index != len(lines) - 1:
            content.append({"type": "hardBreak"})

    if not content:
        content.append({"type": "text", "text": ""})

    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": content,
            }
        ],
    }


def human_join(items: Iterable[str]) -> str:
    """Return a human readable comma separated list."""
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" and {items[-1]}"
