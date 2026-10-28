"""Laboratory information screen (SRS 6.1.1)."""

from __future__ import annotations

from tkinter import ttk

from .. import lab_info
from ..roles import Role
from .common import PAD, Form, run


class LabInfoTab(ttk.Frame):
    title = "Laboratory"

    def __init__(self, master, app):
        super().__init__(master, padding=12)
        self.app = app
        ttk.Label(self, text="Laboratory information", style="Heading.TLabel").pack(anchor="w")
        self.note = ttk.Label(self, foreground="#666")
        self.note.pack(anchor="w", pady=(0, 8))
        self.form = Form(self, [(k, lab_info.LABELS[k], "entry") for k in lab_info.FIELDS], width=50)
        self.form.pack(anchor="w", fill="x")
        bar = ttk.Frame(self)
        bar.pack(anchor="w", pady=8)
        self.save_btn = ttk.Button(bar, text="Save", command=self.save)
        self.save_btn.pack(side="left", **PAD)
        ttk.Button(bar, text="Revert", command=self.refresh).pack(side="left", **PAD)

    def refresh(self):
        self.form.set(lab_info.get(self.app.conn).__dict__)

    def on_user_changed(self):
        is_manager = self.app.user.role == Role.LAB_MANAGER
        self.form.set_enabled(is_manager)
        self.save_btn.state(["!disabled"] if is_manager else ["disabled"])
        self.note.configure(
            text="You can edit and save these details." if is_manager
            else "Read-only: only the laboratory manager can change these details."
        )

    def save(self):
        info = lab_info.LabInfo(**self.form.get())
        saved = run(self, lab_info.update, self.app.conn, self.app.user, info, success="Laboratory information saved.")
        if saved:
            self.form.set(saved.__dict__)
            self.app.refresh_title()
