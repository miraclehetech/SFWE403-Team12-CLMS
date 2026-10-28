"""Test intake and tracking screen (SRS 6.3.1, 6.3.2 and the Oct 1st field list)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import lab_tests as tr, patients
from ..database import now
from .common import PAD, Form, FormDialog, Table, run

PHYSICIAN_SPEC = [
    ("physician_id", "Physician ID / license *", "entry"),
    ("name", "Physician name *", "entry"),
    ("phone", "Physician phone", "entry"),
    ("email", "Physician email", "entry"),
    ("practice", "Practice / clinic", "entry"),
]
BILLING_SPEC = [
    ("insurance_provider", "Insurance provider *", "entry"),
    ("insurance_policy_number", "Policy number *", "entry"),
    ("notes", "Notes", "entry"),
]


def _patient_label(p: patients.Patient) -> str:
    return f"#{p.patient_id} - {p.full_name} ({p.date_of_birth})"


class TestRequestsTab(ttk.Frame):
    title = "Test Requests"

    def __init__(self, master, app):
        super().__init__(master, padding=12)
        self.app = app
        self._patients: dict[str, patients.Patient] = {}
        self._tests: dict[str, tr.CatalogTest] = {}

        # ---------------------------------------------------------- intake
        intake = ttk.LabelFrame(self, text="New test request", padding=8)
        intake.pack(fill="x")

        row = ttk.Frame(intake)
        row.pack(fill="x")
        ttk.Label(row, text="Received:").pack(side="left", **PAD)
        self.source = tk.StringVar(value="WALK_IN")
        for key, label in tr.SOURCES.items():
            ttk.Radiobutton(row, text=label, value=key, variable=self.source).pack(side="left", **PAD)

        row = ttk.Frame(intake)
        row.pack(fill="x")
        ttk.Label(row, text="Patient *:").pack(side="left", **PAD)
        self.patient_var = tk.StringVar()
        self.patient_box = ttk.Combobox(row, textvariable=self.patient_var, state="readonly", width=42)
        self.patient_box.pack(side="left", **PAD)
        self.patient_box.bind("<<ComboboxSelected>>", lambda _e: self._fill_insurance())
        ttk.Label(row, text="Test *:").pack(side="left", **PAD)
        self.test_var = tk.StringVar()
        self.test_box = ttk.Combobox(row, textvariable=self.test_var, state="readonly", width=36)
        self.test_box.pack(side="left", **PAD)
        self.test_box.bind("<<ComboboxSelected>>", lambda _e: self._show_test())
        self.test_info = ttk.Label(row, foreground="#666")
        self.test_info.pack(side="left", **PAD)

        cols = ttk.Frame(intake)
        cols.pack(fill="x")
        doc_box = ttk.LabelFrame(cols, text="Ordering physician", padding=4)
        doc_box.pack(side="left", fill="both", expand=True)
        self.doctor = Form(doc_box, PHYSICIAN_SPEC, width=26)
        self.doctor.pack(fill="x")
        self.doctor.widgets["physician_id"].bind("<FocusOut>", lambda _e: self._lookup_physician())
        bill_box = ttk.LabelFrame(cols, text="Health insurance / billing", padding=4)
        bill_box.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.billing = Form(bill_box, BILLING_SPEC, width=26)
        self.billing.pack(fill="x")
        ttk.Label(bill_box, text="Filled in from the patient's account; edit if a new card was presented.",
                  foreground="#666", wraplength=300).pack(anchor="w", padx=6)
        ttk.Button(intake, text="Accept test request", command=self.submit).pack(anchor="e", pady=(6, 0))

        # ---------------------------------------------------------- list + details
        lower = ttk.Frame(self)
        lower.pack(fill="both", expand=True, pady=(10, 0))
        left = ttk.Frame(lower)
        left.pack(side="left", fill="both", expand=True)
        bar = ttk.Frame(left)
        bar.pack(fill="x")
        ttk.Label(bar, text="Show:").pack(side="left")
        self.status_filter = tk.StringVar(value="all")
        box = ttk.Combobox(bar, textvariable=self.status_filter, values=["all", *tr.STATUSES], state="readonly", width=12)
        box.pack(side="left", **PAD)
        box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_list())
        self.table = Table(left, [("id", "Report ID", 170), ("date", "Report date", 125), ("patient", "Patient", 110),
                                  ("test", "Test", 150), ("doctor", "Physician", 105), ("src", "Source", 60),
                                  ("status", "Status", 75)], height=9)
        self.table.pack(fill="both", expand=True, pady=4)
        self.table.bind_select(self.show_details)

        right = ttk.Frame(lower)
        right.pack(side="left", fill="both", padx=(10, 0))
        self.details = tk.Text(right, width=48, height=14, wrap="word", font="TkFixedFont")
        self.details.pack(fill="both", expand=True)
        self.details.configure(state="disabled")
        acts = ttk.Frame(right)
        acts.pack(fill="x", pady=4)
        for col, (label, cmd) in enumerate((("Collection...", self.collect), ("Result...", self.enter_result),
                                            ("Validate", self.validate))):
            ttk.Button(acts, text=label, command=cmd).grid(row=0, column=col, sticky="we", padx=2)
            acts.columnconfigure(col, weight=1)

    # ------------------------------------------------------------------ refresh
    def refresh(self):
        self._patients = {_patient_label(p): p for p in patients.search(self.app.conn)}
        self.patient_box.configure(values=list(self._patients))
        if self.patient_var.get() not in self._patients:
            self.patient_var.set("")
        self._tests = {str(t): t for t in tr.list_catalog(self.app.conn)}
        self.test_box.configure(values=list(self._tests))
        self.refresh_list()

    def refresh_list(self):
        status = self.status_filter.get()
        rows = tr.list_requests(self.app.conn, status=None if status == "all" else status)
        self.table.fill(
            (r.report_id, (r.report_id, r.report_datetime, r.patient_name, r.test_name, r.physician_name,
                           "Phone" if r.source == "PHONE" else "Walk-in", r.result_status))
            for r in rows
        )

    def on_user_changed(self):
        pass

    # ------------------------------------------------------------------ intake helpers
    def _fill_insurance(self):
        p = self._patients.get(self.patient_var.get())
        if p:
            self.billing.set({"insurance_provider": p.insurance_provider,
                              "insurance_policy_number": p.insurance_policy_number})

    def _show_test(self):
        t = self._tests.get(self.test_var.get())
        if t:
            ref = f", ref. {t.reference_range}" if t.reference_range else ""
            self.test_info.configure(text=f"Sample: {t.sample_type}{ref}")

    def _lookup_physician(self):
        doc = tr.get_physician(self.app.conn, self.doctor.vars["physician_id"].get())
        if doc and not self.doctor.vars["name"].get():
            self.doctor.set(doc.__dict__)

    def select_patient(self, patient_id: int):
        for label, p in self._patients.items():
            if p.patient_id == patient_id:
                self.patient_var.set(label)
                self._fill_insurance()

    def submit(self):
        patient = self._patients.get(self.patient_var.get())
        test = self._tests.get(self.test_var.get())
        if not patient or not test:
            run(self, _raise, "Choose a patient and a test.")
            return
        bill = self.billing.get()
        req = run(
            self, tr.accept_test, self.app.conn, self.app.user,
            source=self.source.get(), patient_id=patient.patient_id,
            physician=tr.Physician(**self.doctor.get()), test_code=test.test_code,
            insurance_provider=bill["insurance_provider"],
            insurance_policy_number=bill["insurance_policy_number"], notes=bill["notes"],
        )
        if req:
            self.app.status.set(f"Accepted {req.report_id}: {req.test_name} for {req.patient_name}.")
            self.test_var.set("")
            self.test_info.configure(text="")
            self.billing.vars["notes"].set("")
            self.refresh_list()
            self.table.tree.selection_set(req.report_id)
            self.app.data_changed(skip=self)

    # ------------------------------------------------------------------ details / lifecycle
    def _selected(self) -> tr.TestRequest | None:
        iid = self.table.selected()
        if not iid:
            run(self, _raise, "Select a test request in the list first.")
            return None
        return run(self, tr.get, self.app.conn, iid)

    def show_details(self, iid):
        if not iid:
            return
        r = tr.get(self.app.conn, iid)
        text = "\n".join([
            "REPORT INFORMATION",
            f"  Report ID:        {r.report_id}",
            f"  Reported at:      {r.report_datetime}",
            f"  Received:         {'Phoned in' if r.source == 'PHONE' else 'Walk-in'}",
            f"  Entered by:       {r.entered_by}",
            "PATIENT INFORMATION",
            f"  Patient ID:       {r.patient_id if r.patient_id is not None else '(account removed)'}",
            f"  Name:             {r.patient_name}",
            f"  Date of birth:    {r.patient_dob}  (age {r.patient_age})",
            f"  Gender:           {r.patient_gender}",
            "ORDERING PHYSICIAN",
            f"  Physician ID:     {r.physician_id}",
            f"  Name:             {r.physician_name}",
            "TEST EXECUTION",
            f"  Sample type:      {r.sample_type}",
            f"  Sample ID:        {r.sample_id or '-'}",
            f"  Collected:        {r.collection_datetime or '-'}",
            f"  Collected by:     {r.collected_by or '-'}",
            f"  Performed by:     {r.performed_by or '-'}",
            f"  Machine used:     {r.machine_used or '-'}",
            "TEST RESULTS",
            f"  Test:             {r.test_name}",
            f"  Result:           {r.result_value or '-'} {r.result_units}",
            f"  Reference range:  {r.reference_range or '-'}",
            f"  Status:           {r.result_status}" + (f" by {r.validated_by}" if r.validated_by else ""),
            f"  Results received: {r.results_received_datetime or '-'}",
            "HEALTH INSURANCE / BILLING",
            f"  Provider:         {r.insurance_provider}",
            f"  Policy number:    {r.insurance_policy_number}",
        ] + ([f"NOTES\n  {r.notes}"] if r.notes else []))
        # Tighten the label column so the panel fits without wrapping.
        text = "\n".join(
            f"  {line.split(':', 1)[0].strip() + ':':<15}{line.split(':', 1)[1].strip()}"
            if line.startswith("  ") and ":" in line else line
            for line in text.splitlines()
        )
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _after_change(self, req):
        if req:
            self.refresh_list()
            self.table.tree.selection_set(req.report_id)
            self.show_details(req.report_id)

    def collect(self):
        req = self._selected()
        if not req:
            return
        values = FormDialog.ask(self, f"Collect sample - {req.report_id}", [
            ("sample_id", "Sample ID / barcode *", "entry"),
            ("collected_by", "Collected by (ID/name) *", "entry"),
            ("collection_datetime", "Collected at (YYYY-MM-DD HH:MM)", "entry"),
        ], initial={"sample_id": req.sample_id, "collected_by": req.collected_by or self.app.user.display_name,
                    "collection_datetime": req.collection_datetime or now()})
        if values:
            self._after_change(run(self, tr.record_collection, self.app.conn, self.app.user, req.report_id,
                                   success="Sample collection recorded.", **values))

    def enter_result(self):
        req = self._selected()
        if not req:
            return
        values = FormDialog.ask(self, f"Enter result - {req.report_id}", [
            ("result_value", "Result value *", "entry"),
            ("result_units", "Units", "entry"),
            ("performed_by", "Performed by (ID) *", "entry"),
            ("machine_used", "Machine / instrument *", "entry"),
            ("results_received_datetime", "Received at (YYYY-MM-DD HH:MM)", "entry"),
        ], initial={"result_value": req.result_value, "result_units": req.result_units,
                    "performed_by": req.performed_by or self.app.user.username,
                    "machine_used": req.machine_used, "results_received_datetime": now()},
            intro=f"{req.test_name} - reference range {req.reference_range or 'n/a'}")
        if values:
            self._after_change(run(self, tr.record_result, self.app.conn, self.app.user, req.report_id,
                                   success="Result recorded.", **values))

    def validate(self):
        req = self._selected()
        if req:
            self._after_change(run(self, tr.validate_result, self.app.conn, self.app.user, req.report_id,
                                   success=f"{req.report_id} validated."))


def _raise(message: str):
    from ..errors import ValidationError
    raise ValidationError(message)
