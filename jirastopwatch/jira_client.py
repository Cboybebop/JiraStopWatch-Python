"""A lightweight Jira REST API client used by the desktop application."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

from .utils import Worklog, make_comment_payload, make_timestamp

LOGGER = logging.getLogger(__name__)


@dataclass
class JiraFilter:
    id: str
    name: str


@dataclass
class JiraIssue:
    key: str
    summary: str


class JiraClient:
    """Small helper around Jira's REST API endpoints used by the app."""

    def __init__(self, base_url: str, email: str, api_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.api_token = api_token
        self._session = requests.Session()
        self._session.auth = HTTPBasicAuth(self.email, self.api_token)
        self._session.headers.update({"Accept": "application/json"})

    def is_configured(self) -> bool:
        return bool(self.base_url and self.email and self.api_token)

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        if not self.is_configured():
            raise RuntimeError("Jira client is not configured")
        url = f"{self.base_url}{path}"
        LOGGER.debug("Jira request %s %s", method, url)
        response = self._session.request(method, url, timeout=20, **kwargs)
        if response.status_code >= 400:
            LOGGER.error("Jira API call failed: %s", response.text)
            response.raise_for_status()
        return response

    def fetch_filters(self) -> list[JiraFilter]:
        data = self._request("GET", "/rest/api/3/filter/favourite").json()
        return [JiraFilter(id=item["id"], name=item["name"]) for item in data]

    def fetch_filter_jql(self, filter_id: str) -> str:
        data = self._request("GET", f"/rest/api/3/filter/{filter_id}").json()
        return data.get("jql", "")

    def fetch_issues(self, jql: str, max_results: int = 50) -> list[JiraIssue]:
        payload = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ["summary"],
        }
        data = self._request("POST", "/rest/api/3/search", json=payload).json()
        issues = []
        for issue in data.get("issues", []):
            fields = issue.get("fields", {})
            issues.append(JiraIssue(key=issue["key"], summary=fields.get("summary", "")))
        return issues

    def fetch_issue(self, issue_key: str) -> JiraIssue:
        data = self._request("GET", f"/rest/api/3/issue/{issue_key}").json()
        return JiraIssue(key=data["key"], summary=data.get("fields", {}).get("summary", ""))

    def post_worklog(self, worklog: Worklog) -> str:
        payload = {
            "timeSpentSeconds": worklog.seconds,
            "started": make_timestamp(worklog.started),
            "adjustEstimate": worklog.adjust_estimate,
        }
        comment_payload = make_comment_payload(worklog.comment)
        if comment_payload is not None:
            payload["comment"] = comment_payload
        if worklog.adjust_estimate == "new" and worklog.remaining_estimate is not None:
            payload["remainingEstimateSeconds"] = worklog.remaining_estimate
        response = self._request("POST", f"/rest/api/3/issue/{worklog.issue_key}/worklog", json=payload)
        return response.json().get("id", "")

    def transition_to_in_progress(self, issue_key: str) -> None:
        transitions = self._request("GET", f"/rest/api/3/issue/{issue_key}/transitions").json()
        transition_id: Optional[str] = None
        for transition in transitions.get("transitions", []):
            name = transition.get("name", "").lower()
            if "in progress" in name:
                transition_id = transition.get("id")
                break
        if not transition_id:
            LOGGER.info("No 'In Progress' transition available for %s", issue_key)
            return
        payload = {"transition": {"id": transition_id}}
        self._request("POST", f"/rest/api/3/issue/{issue_key}/transitions", json=payload)

    def test_authentication(self) -> bool:
        try:
            self._request("GET", "/rest/api/3/myself")
            return True
        except Exception:
            LOGGER.exception("Authentication test failed")
            return False
