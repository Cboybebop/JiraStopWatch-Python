"""Graphical desktop application for JiraStopWatch."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable, Iterable, Optional
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .jira_client import JiraClient, JiraFilter, JiraIssue
from .models import AppSettings, PendingWorklog, TimerState
from .storage import (
    load_pending_worklogs,
    load_settings,
    load_state,
    save_pending_worklogs,
    save_settings,
    save_state,
)
from .utils import Worklog, format_duration, parse_duration

LOGGER = logging.getLogger(__name__)


class JiraStopWatchApp(tk.Tk):
    """Main application window."""

    TICK_INTERVAL_MS = 1000

    def __init__(self) -> None:
        super().__init__()
        self.title("Jira StopWatch")
        self.geometry("1040x720")
        self.minsize(900, 600)
        self.configure(padx=12, pady=12)

        self.settings: AppSettings = load_settings()
        self.client = JiraClient(
            self.settings.base_url,
            self.settings.email,
            self.settings.api_token,
        )
        self.status_var = tk.StringVar(value="Ready.")
        self.timers: list[TimerRow] = []
        self.pending_worklogs: list[PendingWorklog] = load_pending_worklogs()

        self._build_ui()
        self._load_timers()
        self._update_pending_panel()

        self.after(self.TICK_INTERVAL_MS, self._tick)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        menu_bar = tk.Menu(self)
        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="Settings", command=self.open_settings_dialog)
        file_menu.add_command(label="Test Connection", command=self.test_connection)
        file_menu.add_command(label="Clear Settings", command=self.clear_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menu_bar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menu_bar, tearoff=False)
        help_menu.add_command(label="About", command=self.show_about)
        menu_bar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menu_bar)

        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Add Timer", command=self.add_timer).pack(side="left")
        ttk.Button(toolbar, text="Pause All", command=self.pause_all).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(
            toolbar,
            text="Post Pending Worklogs",
            command=self.post_pending_worklogs,
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            toolbar,
            text="Reset All Timers",
            command=self.reset_all_timers,
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            toolbar,
            text="Remove All Timers",
            command=self.remove_all_timers,
        ).pack(side="left", padx=(8, 0))

        self.timer_canvas = tk.Canvas(self, highlightthickness=0)
        self.timer_canvas.pack(fill="both", expand=True, pady=(12, 12))
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.timer_canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.timer_canvas.configure(yscrollcommand=scrollbar.set)
        self.timer_container = ttk.Frame(self.timer_canvas)
        self.timer_canvas.create_window((0, 0), window=self.timer_container, anchor="nw")
        self.timer_container.bind(
            "<Configure>",
            lambda e: self.timer_canvas.configure(scrollregion=self.timer_canvas.bbox("all")),
        )

        self.pending_panel = PendingWorklogPanel(self, controller=self)
        self.pending_panel.pack(fill="x", pady=(0, 12))

        status_bar = ttk.Label(self, textvariable=self.status_var, anchor="w")
        status_bar.pack(fill="x")

    def _load_timers(self) -> None:
        states = load_state()
        now = time.time()
        if not states:
            states = [TimerState()]
        for state in states:
            if state.running and state.last_started:
                elapsed = max(0, now - float(state.last_started))
                state.seconds += int(elapsed)
                state.last_started = now
            self.add_timer(state)

    # ---------------------------------------------------------------- timers --
    def add_timer(self, state: Optional[TimerState] = None) -> None:
        state = state or TimerState()
        row = TimerRow(self.timer_container, controller=self, state=state)
        row.pack(fill="x", pady=6)
        self.timers.append(row)
        self._update_timer_indices()

    def remove_timer(self, row: "TimerRow") -> None:
        if messagebox.askyesno("Remove timer", "Are you sure you want to remove this timer?"):
            row.destroy()
            self.timers.remove(row)
            self._update_timer_indices()
            self.persist_state()

    def _update_timer_indices(self) -> None:
        for index, row in enumerate(self.timers, start=1):
            row.update_index(index)

    def pause_all(self) -> None:
        for row in self.timers:
            row.pause_timer()
        self.persist_state()

    def reset_all_timers(self) -> None:
        if not self.timers:
            messagebox.showinfo("Reset timers", "There are no timers to reset.")
            return
        if not messagebox.askyesno(
            "Reset all timers",
            "Reset tracked time for all timers?",
        ):
            return
        for row in self.timers:
            row.state.seconds = 0
            row.state.running = False
            row.state.last_started = None
            row.refresh_display()
        self.persist_state()
        self.set_status("All timers have been reset")

    def remove_all_timers(self) -> None:
        if not self.timers:
            messagebox.showinfo("Remove timers", "There are no timers to remove.")
            return
        if not messagebox.askyesno(
            "Remove all timers",
            "Remove every timer from the list?",
        ):
            return
        for row in list(self.timers):
            row.destroy()
        self.timers.clear()
        self.persist_state()
        self.set_status("All timers have been removed")

    def timer_started(self, row: "TimerRow") -> None:
        # Optionally update issue status when timer starts.
        issue_key = row.state.issue_key
        if issue_key:
            self.set_status(f"Setting {issue_key} to In Progress…")
            self.run_in_background(
                self.client.transition_to_in_progress,
                issue_key,
                on_success=lambda _: self.set_status(f"Timer started for {issue_key}"),
                on_error=lambda exc: self._handle_error(
                    "Failed to transition issue", exc
                ),
            )
        for other in self.timers:
            if other is not row and other.state.running:
                other.pause_timer()
        self.persist_state()

    def timer_paused(self, row: "TimerRow") -> None:
        self.persist_state()

    def persist_state(self) -> None:
        save_state([row.state for row in self.timers])
        save_settings(self.settings)
        save_pending_worklogs(self.pending_worklogs)

    def _tick(self) -> None:
        for row in self.timers:
            row.refresh_display()
        self.after(self.TICK_INTERVAL_MS, self._tick)

    # ----------------------------------------------------------- interactions --
    def on_issue_changed(self, row: "TimerRow", issue_key: str) -> None:
        issue_key = issue_key.strip()
        row.set_issue_key(issue_key)
        if not issue_key:
            row.set_description("")
            self.persist_state()
            return

        def _fetch_issue() -> JiraIssue:
            return self.client.fetch_issue(issue_key)

        self.set_status(f"Fetching issue {issue_key}…")
        self.run_in_background(
            _fetch_issue,
            on_success=lambda issue: self._apply_issue_details(row, issue),
            on_error=lambda exc: self._handle_error(
                f"Failed to fetch {issue_key}", exc, reset_description=True, row=row
            ),
        )

    def _apply_issue_details(self, row: "TimerRow", issue: JiraIssue) -> None:
        row.set_issue_key(issue.key)
        row.set_description(issue.summary)
        self.settings.filter_cache.setdefault(issue.key, issue.summary)
        self.persist_state()
        self.set_status(f"Loaded {issue.key}")

    def open_issue_picker(self, row: "TimerRow") -> None:
        if not self.client.is_configured():
            messagebox.showerror(
                "Configuration missing",
                "Please configure Jira access in the Settings dialog first.",
            )
            return
        dialog = IssuePickerDialog(self, current_issue=row.state.issue_key)
        self.wait_window(dialog)
        if dialog.result:
            row.issue_var.set(dialog.result)
            self.on_issue_changed(row, dialog.result)

    def post_worklog(self, row: "TimerRow") -> None:
        if not row.state.issue_key:
            messagebox.showerror("Issue missing", "Please select an issue before posting.")
            return
        if not self.client.is_configured():
            messagebox.showerror(
                "Configuration missing",
                "Please configure Jira access in the Settings dialog first.",
            )
            return
        dialog = WorklogDialog(self, row)
        self.wait_window(dialog)
        if not dialog.result:
            return
        worklog, save_for_later = dialog.result

        if save_for_later:
            self.save_worklog_for_later(worklog)
            return

        self.set_status(f"Posting worklog for {worklog.issue_key}…")

        def _post() -> str:
            return self.client.post_worklog(worklog)

        self.run_in_background(
            _post,
            on_success=lambda worklog_id: self._worklog_posted(worklog, worklog_id, row),
            on_error=lambda exc: self._handle_worklog_failure(worklog, exc),
        )

    def _worklog_posted(self, worklog: Worklog, worklog_id: str, row: "TimerRow") -> None:
        self.set_status(
            f"Posted {format_duration(worklog.seconds)} to {worklog.issue_key} (id {worklog_id})"
        )
        row.reset_timer()
        self.persist_state()

    def _handle_worklog_failure(self, worklog: Worklog, exc: BaseException) -> None:
        self.save_worklog_for_later(worklog)
        self._handle_error("Failed to post worklog", exc)

    def save_worklog_for_later(self, worklog: Worklog) -> None:
        pending = PendingWorklog(
            issue_key=worklog.issue_key,
            seconds=worklog.seconds,
            comment=worklog.comment,
            created_at=datetime.now(),
        )
        self.pending_worklogs.append(pending)
        self._update_pending_panel()
        self.persist_state()
        self.set_status(
            f"Saved {format_duration(worklog.seconds)} for {worklog.issue_key} to pending queue"
        )

    def post_pending_worklogs(self) -> None:
        if not self.pending_worklogs:
            messagebox.showinfo("Pending worklogs", "There are no pending worklogs to post.")
            return
        if not self.client.is_configured():
            messagebox.showerror(
                "Configuration missing",
                "Please configure Jira access before posting pending worklogs.",
            )
            return

        worklogs = list(self.pending_worklogs)
        self.set_status(f"Posting {len(worklogs)} pending worklog(s)…")

        def _post_all() -> list[str]:
            ids = []
            for worklog in worklogs:
                payload = Worklog(
                    issue_key=worklog.issue_key,
                    seconds=worklog.seconds,
                    comment=worklog.comment,
                    started=datetime.now(),
                    adjust_estimate="auto",
                    remaining_estimate=None,
                )
                ids.append(self.client.post_worklog(payload))
            return ids

        self.run_in_background(
            _post_all,
            on_success=lambda ids: self._pending_worklogs_posted(ids),
            on_error=lambda exc: self._handle_error("Failed to post pending worklogs", exc),
        )

    def _pending_worklogs_posted(self, worklog_ids: Iterable[str]) -> None:
        count = len(list(worklog_ids))
        self.pending_worklogs.clear()
        self._update_pending_panel()
        self.persist_state()
        self.set_status(f"Successfully posted {count} pending worklog(s)")

    # --------------------------------------------------------------- settings --
    def open_settings_dialog(self) -> None:
        dialog = SettingsDialog(self, self.settings)
        self.wait_window(dialog)
        if dialog.result:
            self.settings = dialog.result
            save_settings(self.settings)
            self.client = JiraClient(
                self.settings.base_url,
                self.settings.email,
                self.settings.api_token,
            )
            self.persist_state()

    def test_connection(self) -> None:
        if not self.client.is_configured():
            messagebox.showerror(
                "Configuration missing",
                "Please configure Jira access in the Settings dialog first.",
            )
            return
        self.set_status("Testing Jira connection…")

        self.run_in_background(
            self.client.test_authentication,
            on_success=lambda ok: self.set_status(
                "Successfully authenticated with Jira" if ok else "Authentication failed"
            ),
            on_error=lambda exc: self._handle_error("Failed to test connection", exc),
        )

    def clear_settings(self) -> None:
        if not messagebox.askyesno(
            "Clear settings",
            "Clear all saved Jira connection settings?",
        ):
            return
        self.settings = AppSettings()
        self.client = JiraClient(
            self.settings.base_url,
            self.settings.email,
            self.settings.api_token,
        )
        self.persist_state()
        self.set_status("Settings cleared. Configure Jira to continue.")

    def show_about(self) -> None:
        messagebox.showinfo(
            "About Jira StopWatch",
            "Track time against Jira issues, browse favourite filters and post worklogs.",
        )

    # ------------------------------------------------------- pending worklogs --
    def _update_pending_panel(self) -> None:
        self.pending_panel.refresh(self.pending_worklogs)

    def remove_pending_by_indices(self, indices: Iterable[int]) -> None:
        for index in sorted(indices, reverse=True):
            if 0 <= index < len(self.pending_worklogs):
                self.pending_worklogs.pop(index)
        self._update_pending_panel()
        self.persist_state()

    # ----------------------------------------------------------- housekeeping --
    def run_in_background(
        self,
        func: Callable,
        *args,
        on_success: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
    ) -> None:
        def task() -> None:
            try:
                result = func(*args)
            except Exception as exc:  # pragma: no cover - UI feedback
                LOGGER.exception("Background task failed")
                if on_error:
                    self.after(0, lambda: on_error(exc))
            else:
                if on_success:
                    self.after(0, lambda: on_success(result))

        threading.Thread(target=task, daemon=True).start()

    def _handle_error(
        self,
        message: str,
        exc: BaseException,
        *,
        reset_description: bool = False,
        row: Optional["TimerRow"] = None,
    ) -> None:
        LOGGER.exception(message)
        messagebox.showerror(message, str(exc))
        self.set_status(message)
        if reset_description and row:
            row.set_description("")
        self.persist_state()

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def on_close(self) -> None:
        for row in self.timers:
            row.prepare_for_exit()
        self.persist_state()
        self.destroy()


class TimerRow(ttk.Frame):
    """Widget representing a single timer slot."""

    def __init__(self, master: tk.Misc, controller: JiraStopWatchApp, state: TimerState) -> None:
        super().__init__(master, padding=8, relief="groove")
        self.controller = controller
        self.state = state
        self.issue_var = tk.StringVar(value=state.issue_key)
        self.time_var = tk.StringVar(value=format_duration(state.seconds))
        self.comment_var = tk.StringVar(value=state.comment)
        self.description_var = tk.StringVar(value=state.description or "")
        self.index_var = tk.StringVar(value="")

        self._build_row()
        self.refresh_display()

    def _build_row(self) -> None:
        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, textvariable=self.index_var, width=4, anchor="center").pack(
            side="left"
        )
        issue_entry = ttk.Entry(header, textvariable=self.issue_var, width=18)
        issue_entry.pack(side="left")
        issue_entry.bind("<Return>", lambda *_: self.controller.on_issue_changed(self, self.issue_var.get()))
        issue_entry.bind("<FocusOut>", lambda *_: self.controller.on_issue_changed(self, self.issue_var.get()))
        ttk.Button(header, text="Browse…", command=lambda: self.controller.open_issue_picker(self)).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(header, textvariable=self.description_var, anchor="w").pack(
            side="left", padx=(12, 0), fill="x", expand=True
        )

        body = ttk.Frame(self)
        body.pack(fill="x", pady=(6, 0))
        time_label = ttk.Label(body, textvariable=self.time_var, font=("Segoe UI", 16, "bold"))
        time_label.pack(side="left")
        time_label.bind("<Double-Button-1>", lambda *_: self.edit_duration())

        self.start_button = ttk.Button(body, text="Start", command=self.toggle_timer, width=8)
        self.start_button.pack(side="left", padx=(12, 0))
        ttk.Button(body, text="Reset", command=self.reset_timer, width=8).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(body, text="Post", command=lambda: self.controller.post_worklog(self)).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(body, text="Save", command=self.save_comment).pack(side="left", padx=(6, 0))
        ttk.Button(body, text="Remove", command=lambda: self.controller.remove_timer(self)).pack(
            side="left", padx=(6, 0)
        )

        comment_entry = ttk.Entry(body, textvariable=self.comment_var)
        comment_entry.pack(side="left", padx=(12, 0), fill="x", expand=True)
        comment_entry.bind("<FocusOut>", lambda *_: self.save_comment())

    # ----------------------------------------------------------------- actions --
    def update_index(self, index: int) -> None:
        self.index_var.set(f"#{index}")

    def toggle_timer(self) -> None:
        if self.state.running:
            self.pause_timer()
        else:
            self.start_timer()

    def start_timer(self) -> None:
        if not self.state.issue_key:
            messagebox.showerror("Issue missing", "Please enter an issue key first.")
            return
        self.state.running = True
        self.state.last_started = time.time()
        self.controller.timer_started(self)
        self._update_start_button()

    def pause_timer(self) -> None:
        if not self.state.running:
            return
        elapsed = 0
        if self.state.last_started:
            elapsed = int(time.time() - float(self.state.last_started))
        self.state.seconds += max(0, elapsed)
        self.state.running = False
        self.state.last_started = None
        self.refresh_display()
        self._update_start_button()
        self.controller.timer_paused(self)

    def reset_timer(self) -> None:
        if messagebox.askyesno("Reset timer", "Reset tracked time for this issue?"):
            self.state.seconds = 0
            self.state.running = False
            self.state.last_started = None
            self.refresh_display()
            self._update_start_button()
            self.controller.persist_state()

    def prepare_for_exit(self) -> None:
        if self.state.running and self.state.last_started:
            elapsed = int(time.time() - float(self.state.last_started))
            self.state.seconds += max(0, elapsed)
            self.state.last_started = time.time()

    def refresh_display(self) -> None:
        seconds = self.state.seconds
        if self.state.running and self.state.last_started:
            seconds += int(time.time() - float(self.state.last_started))
        self.time_var.set(format_duration(seconds))
        self._update_start_button()

    def _update_start_button(self) -> None:
        button: ttk.Button = self.start_button
        button.configure(text="Pause" if self.state.running else "Start")

    def edit_duration(self) -> None:
        value = simpledialog.askstring(
            "Edit duration",
            "Enter a Jira formatted duration (e.g. 1h 30m):",
            initialvalue=self.time_var.get(),
            parent=self,
        )
        if not value:
            return
        try:
            seconds = parse_duration(value)
        except ValueError as exc:
            messagebox.showerror("Invalid duration", str(exc))
            return
        self.state.seconds = seconds
        self.state.last_started = time.time() if self.state.running else None
        self.refresh_display()
        self.controller.persist_state()

    def set_issue_key(self, issue_key: str) -> None:
        self.state.issue_key = issue_key
        self.issue_var.set(issue_key)

    def set_description(self, description: str) -> None:
        self.state.description = description
        self.description_var.set(description)

    def save_comment(self) -> None:
        self.state.comment = self.comment_var.get()
        self.controller.persist_state()

    @property
    def current_seconds(self) -> int:
        seconds = self.state.seconds
        if self.state.running and self.state.last_started:
            seconds += int(time.time() - float(self.state.last_started))
        return seconds


class SettingsDialog(tk.Toplevel):
    """Dialog that allows configuring Jira connection details."""

    def __init__(self, master: JiraStopWatchApp, settings: AppSettings) -> None:
        super().__init__(master)
        self.title("Settings")
        self.transient(master)
        self.grab_set()
        self.result: Optional[AppSettings] = None

        self.base_url_var = tk.StringVar(value=settings.base_url)
        self.email_var = tk.StringVar(value=settings.email)
        self.token_var = tk.StringVar(value=settings.api_token)

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Jira Cloud base URL:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.base_url_var, width=40).grid(
            row=0, column=1, sticky="ew"
        )

        ttk.Label(frame, text="Email address:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(frame, textvariable=self.email_var, width=40).grid(
            row=1, column=1, sticky="ew", pady=(6, 0)
        )

        ttk.Label(frame, text="API token:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(frame, textvariable=self.token_var, width=40, show="*").grid(
            row=2, column=1, sticky="ew", pady=(6, 0)
        )

        frame.columnconfigure(1, weight=1)

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(button_row, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(button_row, text="Save", command=self._save).pack(
            side="right", padx=(0, 6)
        )

    def _save(self) -> None:
        base_url = self.base_url_var.get().strip()
        email = self.email_var.get().strip()
        token = self.token_var.get().strip()
        if not (base_url and email and token):
            messagebox.showerror("Missing information", "Please fill in all settings fields.")
            return
        settings = AppSettings(
            base_url=base_url,
            email=email,
            api_token=token,
            default_filter_id="",
            filter_cache={},
        )
        self.result = settings
        self.destroy()


class IssuePickerDialog(tk.Toplevel):
    """Dialog that allows browsing favourite filters and selecting an issue."""

    def __init__(self, master: JiraStopWatchApp, current_issue: str = "") -> None:
        super().__init__(master)
        self.title("Select Jira issue")
        self.transient(master)
        self.grab_set()
        self.result: Optional[str] = None
        self.master_app = master

        self.filter_var = tk.StringVar()
        self.issues: list[JiraIssue] = []

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Favourite filter:").grid(row=0, column=0, sticky="w")
        self.filter_combo = ttk.Combobox(frame, textvariable=self.filter_var, state="readonly")
        self.filter_combo.grid(row=0, column=1, sticky="ew")
        ttk.Button(frame, text="Refresh", command=self.load_filters).grid(
            row=0, column=2, padx=(6, 0)
        )

        ttk.Button(frame, text="Load issues", command=self.load_issues).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )

        self.issue_list = tk.Listbox(frame, height=12)
        self.issue_list.grid(row=2, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        self.issue_list.bind("<Double-Button-1>", lambda *_: self._select_issue())

        ttk.Label(frame, text="Or enter issue key:").grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.manual_entry = ttk.Entry(frame)
        self.manual_entry.grid(row=3, column=1, sticky="ew", pady=(12, 0))
        ttk.Button(frame, text="Use", command=lambda: self._set_result(self.manual_entry.get())).grid(
            row=3, column=2, padx=(6, 0), pady=(12, 0)
        )

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(2, weight=1)

        button_row = ttk.Frame(frame)
        button_row.grid(row=4, column=0, columnspan=3, pady=(12, 0), sticky="e")
        ttk.Button(button_row, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(button_row, text="Select", command=self._select_issue).pack(
            side="right", padx=(0, 6)
        )

        self.load_filters()
        if current_issue:
            self.manual_entry.insert(0, current_issue)

    def load_filters(self) -> None:
        def _on_success(filters: list[JiraFilter]) -> None:
            self.filters = filters
            self.filter_combo["values"] = [f"{f.id}: {f.name}" for f in filters]
            if filters:
                self.filter_combo.current(0)

        self.master_app.set_status("Loading favourite filters…")
        self.master_app.run_in_background(
            self.master_app.client.fetch_filters,
            on_success=_on_success,
            on_error=lambda exc: self.master_app._handle_error("Failed to load filters", exc),
        )

    def load_issues(self) -> None:
        selection = self.filter_var.get()
        if not selection:
            messagebox.showerror("No filter selected", "Please select a Jira filter first.")
            return
        filter_id = selection.split(":", 1)[0]

        def _load() -> list[JiraIssue]:
            jql = self.master_app.client.fetch_filter_jql(filter_id)
            issues = self.master_app.client.fetch_issues(jql)
            return issues

        def _on_success(issues: list[JiraIssue]) -> None:
            self.issues = issues
            self.issue_list.delete(0, tk.END)
            for issue in issues:
                self.issue_list.insert(tk.END, f"{issue.key}: {issue.summary}")
            self.master_app.set_status(f"Loaded {len(issues)} issues")

        self.master_app.set_status("Loading issues…")
        self.master_app.run_in_background(
            _load,
            on_success=_on_success,
            on_error=lambda exc: self.master_app._handle_error("Failed to load issues", exc),
        )

    def _select_issue(self) -> None:
        selection = self.issue_list.curselection()
        if not selection:
            if self.manual_entry.get():
                self._set_result(self.manual_entry.get())
            return
        index = selection[0]
        issue = self.issues[index]
        self._set_result(issue.key)

    def _set_result(self, value: str) -> None:
        if not value:
            return
        self.result = value.strip()
        self.destroy()


class WorklogDialog(tk.Toplevel):
    """Dialog that captures worklog information before posting."""

    def __init__(self, master: JiraStopWatchApp, row: TimerRow) -> None:
        super().__init__(master)
        self.title("Post worklog")
        self.transient(master)
        self.grab_set()
        self.result: Optional[tuple[Worklog, bool]] = None
        self.row = row

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=f"Issue: {row.state.issue_key}").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text=f"Summary: {row.state.description}").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )

        ttk.Label(frame, text="Time spent:").grid(row=2, column=0, sticky="w")
        self.time_var = tk.StringVar(value=format_duration(row.current_seconds))
        ttk.Entry(frame, textvariable=self.time_var, width=20).grid(row=2, column=1, sticky="w")

        ttk.Label(frame, text="Started (ISO 8601):").grid(row=3, column=0, sticky="w", pady=(6, 0))
        default_started = datetime.now().astimezone().isoformat(timespec="minutes")
        self.started_var = tk.StringVar(value=default_started)
        ttk.Entry(frame, textvariable=self.started_var, width=30).grid(
            row=3, column=1, sticky="w", pady=(6, 0)
        )

        ttk.Label(frame, text="Adjust remaining estimate:").grid(
            row=4, column=0, sticky="w", pady=(6, 0)
        )
        self.adjust_var = tk.StringVar(value="auto")
        adjust_combo = ttk.Combobox(
            frame,
            textvariable=self.adjust_var,
            values=("auto", "leave", "new"),
            state="readonly",
            width=18,
        )
        adjust_combo.grid(row=4, column=1, sticky="w", pady=(6, 0))
        adjust_combo.bind("<<ComboboxSelected>>", lambda *_: self._update_remaining_state())

        ttk.Label(frame, text="New remaining estimate:").grid(
            row=5, column=0, sticky="w", pady=(6, 0)
        )
        self.remaining_var = tk.StringVar()
        self.remaining_entry = ttk.Entry(frame, textvariable=self.remaining_var, width=20, state="disabled")
        self.remaining_entry.grid(row=5, column=1, sticky="w", pady=(6, 0))

        ttk.Label(frame, text="Comment:").grid(row=6, column=0, sticky="nw", pady=(6, 0))
        self.comment_text = tk.Text(frame, width=50, height=6)
        self.comment_text.grid(row=6, column=1, sticky="ew", pady=(6, 0))
        if row.state.comment:
            self.comment_text.insert("1.0", row.state.comment)

        self.save_for_later_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text="Save comment with timestamp for later posting",
            variable=self.save_for_later_var,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))

        frame.columnconfigure(1, weight=1)

        button_row = ttk.Frame(frame)
        button_row.grid(row=8, column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(button_row, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(button_row, text="Post", command=self._post).pack(side="right", padx=(0, 6))

        self._update_remaining_state()

    def _update_remaining_state(self) -> None:
        state = "normal" if self.adjust_var.get() == "new" else "disabled"
        self.remaining_entry.configure(state=state)

    def _post(self) -> None:
        try:
            seconds = parse_duration(self.time_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid duration", str(exc))
            return
        try:
            started = datetime.fromisoformat(self.started_var.get())
        except ValueError as exc:
            messagebox.showerror("Invalid timestamp", str(exc))
            return
        comment = self.comment_text.get("1.0", "end").strip()
        adjust = self.adjust_var.get()
        remaining_seconds = None
        if adjust == "new":
            try:
                remaining_seconds = parse_duration(self.remaining_var.get())
            except ValueError as exc:
                messagebox.showerror("Invalid remaining estimate", str(exc))
                return
        worklog = Worklog(
            issue_key=self.row.state.issue_key,
            seconds=seconds,
            comment=comment,
            started=started,
            adjust_estimate=adjust,
            remaining_estimate=remaining_seconds,
        )
        self.result = (worklog, self.save_for_later_var.get())
        self.destroy()


class PendingWorklogPanel(ttk.Labelframe):
    """Panel that displays pending worklogs saved for later."""

    def __init__(self, master: tk.Misc, controller: JiraStopWatchApp) -> None:
        super().__init__(master, text="Pending worklogs")
        self.controller = controller
        self.listbox = tk.Listbox(self, height=4)
        self.listbox.pack(fill="both", expand=True, padx=6, pady=6)

        button_row = ttk.Frame(self)
        button_row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(button_row, text="Post selected", command=self._post_selected).pack(
            side="left"
        )
        ttk.Button(button_row, text="Remove selected", command=self._remove_selected).pack(
            side="left", padx=(6, 0)
        )

    def refresh(self, worklogs: list[PendingWorklog]) -> None:
        self.listbox.delete(0, tk.END)
        for worklog in worklogs:
            entry = (
                f"{worklog.issue_key} – {format_duration(worklog.seconds)} on "
                f"{worklog.created_at:%Y-%m-%d %H:%M}: {worklog.comment[:60]}"
            )
            self.listbox.insert(tk.END, entry)

    def _post_selected(self) -> None:
        indices = self.listbox.curselection()
        if not indices:
            messagebox.showinfo("No selection", "Please select at least one worklog.")
            return
        selected = [self.controller.pending_worklogs[i] for i in indices]
        if not self.controller.client.is_configured():
            messagebox.showerror(
                "Configuration missing",
                "Configure Jira access before posting pending worklogs.",
            )
            return

        def _post() -> list[str]:
            ids = []
            for worklog in selected:
                payload = Worklog(
                    issue_key=worklog.issue_key,
                    seconds=worklog.seconds,
                    comment=worklog.comment,
                    started=datetime.now(),
                    adjust_estimate="auto",
                    remaining_estimate=None,
                )
                ids.append(self.controller.client.post_worklog(payload))
            return ids

        def _on_success(ids: list[str]) -> None:
            self.controller.set_status(f"Posted {len(ids)} worklog(s)")
            self.controller.remove_pending_by_indices(indices)

        self.controller.run_in_background(
            _post,
            on_success=_on_success,
            on_error=lambda exc: self.controller._handle_error(
                "Failed to post selected worklogs", exc
            ),
        )

    def _remove_selected(self) -> None:
        indices = self.listbox.curselection()
        if not indices:
            return
        self.controller.remove_pending_by_indices(indices)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    app = JiraStopWatchApp()
    app.mainloop()


if __name__ == "__main__":
    main()
