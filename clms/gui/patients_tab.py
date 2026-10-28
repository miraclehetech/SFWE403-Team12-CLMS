"""Patient accounts screen (SRS 6.1.4, 6.1.5)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import patients
from ..errors import CLMSError
from ..validators import GENDERS
from .common import PAD, Form, Table, run, set_status

SPEC = [
    ("first_name", "First name *", "entry"),
    ("last_name", "Last name *", "entry"),
    ("date_of_birth", "Date of birth * (YYYY-MM-DD)", "entry"),
    ("gender", "Gender", "combo", GENDERS),
    ("address", "Address *", "entry"),
    ("phone", "Phone *", "entry"),
    ("email", "Email", "entry"),
    ("insurance_provider", "Insurance provider", "entry"),
    ("insurance_policy_number", "Policy number", "entry"),
    ("insurance_coverage", "Coverage details", "entry"),
]


class PatientsTab(ttk.Frame):
    title = "Patients"

    def __init__(self, master, app):
        super().__init__(master, padding=12)
        self.app = app
        self.current_id: int | None = None

        left = ttk.Frame(self)
        left.pack(side="left", fill="both", expand=True)
        search = ttk.Frame(left)
        search.pack(fill="x")
        ttk.Label(search, text="Search (ID, name, phone, email, policy):").pack(side="left")
        self.query = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.query)
        entry.pack(side="left", fill="x", expand=True, **PAD)
        entry.bind("<Return>", lambda _e: self.refresh())
        ttk.Button(search, text="Search", command=self.refresh).pack(side="left")
        self.table = Table(left, [("id", "ID", 50), ("name", "Name", 160), ("dob", "Date of birth", 95),
                                  ("phone", "Phone", 120), ("ins", "Insurance", 140)], height=18)
        self.table.pack(fill="both", expand=True, pady=6)
        self.table.bind_select(self.load)

        right = ttk.LabelFrame(self, text="Patient account", padding=8)
        right.pack(side="left", fill="y", padx=(12, 0))
        self.header = ttk.Label(right, text="New patient", style="Heading.TLabel")
        self.header.pack(anchor="w")
        self.form = Form(right, SPEC)
        self.form.pack(fill="x")
        ttk.Label(right, text="* required", foreground="#666").pack(anchor="w", padx=6)
        bar = ttk.Frame(right)
        bar.pack(fill="x", pady=8)
        ttk.Button(bar, text="New", command=self.new).pack(side="left", **PAD)
        ttk.Button(bar, text="Save", command=self.save).pack(side="left", **PAD)
        self.delete_btn = ttk.Button(bar, text="Delete patient", command=self.delete)
        self.delete_btn.pack(side="right", **PAD)
        self.new()

    # ------------------------------------------------------------------ data
    def refresh(self):
        rows = patients.search(self.app.conn, self.query.get())
        self.table.fill(
            (p.patient_id, (p.patient_id, p.full_name, p.date_of_birth, p.phone, p.insurance_provider or "-"))
            for p in rows
        )

    def on_user_changed(self):
        allowed = self.app.user.role in patients.CAN_DELETE
        self.delete_btn.state(["!disabled"] if allowed else ["disabled"])

    def new(self):
        self.current_id = None
        self.form.clear()
        self.form.vars["gender"].set("Unknown")
        self.header.configure(text="New patient")
        self.table.tree.selection_remove(self.table.tree.selection())

    def load(self, iid):
        if not iid:
            return
        p = run(self, patients.get, self.app.conn, int(iid))
        if p:
            self.current_id = p.patient_id
            self.form.set(p.__dict__)
            self.header.configure(text=f"Patient #{p.patient_id} - age {p.age}")

    def save(self):
        data = self.form.get()
        p = patients.Patient(**data, patient_id=self.current_id)
        if self.current_id is None:
            saved = run(self, patients.create, self.app.conn, self.app.user, p, success="Patient created.")
        else:
            saved = run(self, patients.update, self.app.conn, self.app.user, p, success="Patient updated.")
        if saved:
            self.refresh()
            self.table.tree.selection_set(str(saved.patient_id))
            self.load(str(saved.patient_id))
            self.app.data_changed()

    def delete(self):
        if self.current_id is None:
            messagebox.showinfo("Delete patient", "Select a patient first.", parent=self)
            return
        name = f"{self.form.vars['first_name'].get()} {self.form.vars['last_name'].get()}"
        if not messagebox.askyesno(
            "Delete patient",
            f"Remove {name} from the system?\n\nExisting test reports and receipts keep their copy "
            "of the patient's details.",
            parent=self,
        ):
            return
        try:
            patients.delete(self.app.conn, self.app.user, self.current_id)
        except CLMSError as exc:
            messagebox.showerror("Cannot continue", str(exc), parent=self)
            return
        set_status(self, f"{name} removed.")
        self.new()
        self.refresh()
        self.app.data_changed()
