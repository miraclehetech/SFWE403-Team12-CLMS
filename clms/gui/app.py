"""Main window: role selector, tabs and status bar (SRS 6.1.2)."""

from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import ttk

from .. import database, lab_info
from ..roles import DEMO_USERS, User
from .lab_info_tab import LabInfoTab
from .patients_tab import PatientsTab
from .pos_tab import POSTab
from .lab_tests_tab import TestRequestsTab


class App(tk.Tk):
    def __init__(self, conn: sqlite3.Connection | None = None, user: User | None = None):
        super().__init__()
        self.conn = conn or database.connect()
        self.user: User = user or DEMO_USERS[0]
        self.geometry("1180x760")
        self.minsize(1000, 640)

        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Heading.TLabel", font=("TkDefaultFont", 11, "bold"))
        style.configure("Banner.TLabel", font=("TkDefaultFont", 14, "bold"))

        top = ttk.Frame(self, padding=(12, 8))
        top.pack(fill="x")
        self.banner = ttk.Label(top, style="Banner.TLabel")
        self.banner.pack(side="left")
        # Until the login story (SFWE12-5/6) is merged, staff pick who they are here.
        self._users = {str(u): u for u in DEMO_USERS}
        self.user_var = tk.StringVar(value=str(self.user))
        if str(self.user) not in self._users:
            self._users[str(self.user)] = self.user
        box = ttk.Combobox(top, textvariable=self.user_var, values=list(self._users), state="readonly", width=40)
        box.pack(side="right")
        box.bind("<<ComboboxSelected>>", lambda _e: self.set_user(self._users[self.user_var.get()]))
        ttk.Label(top, text="Signed in as:").pack(side="right", padx=6)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8)
        self.tabs = [cls(self.notebook, self) for cls in (PatientsTab, TestRequestsTab, POSTab, LabInfoTab)]
        for tab in self.tabs:
            self.notebook.add(tab, text=tab.title)

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w", padding=(8, 2)).pack(fill="x", side="bottom")

        self.refresh_title()
        self.data_changed()
        self.set_user(self.user)

    def refresh_title(self):
        name = lab_info.get(self.conn).name
        self.title(f"{name} - Clinical Laboratory Management System")
        self.banner.configure(text=name)

    def set_user(self, user: User):
        self.user = user
        self.user_var.set(str(user))
        for tab in self.tabs:
            tab.on_user_changed()
        self.status.set(f"Signed in as {user}.")

    def data_changed(self, skip=None):
        """Reload every tab after patients, tests or sales change."""
        for tab in self.tabs:
            if tab is not skip:
                tab.refresh()

    def tab(self, cls):
        return next(t for t in self.tabs if isinstance(t, cls))


def main(db_path: str | None = None):
    conn = database.connect(db_path) if db_path else database.connect()
    App(conn).mainloop()
