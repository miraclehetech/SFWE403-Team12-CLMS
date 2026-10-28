"""SRS 6.1.4 / 6.1.5 - patient accounts (SFWE12-4).

* All laboratory personnel can create and update patient accounts.
* Only a specimen collector or the laboratory manager can remove a patient.
  Test reports and receipts keep a copy of the patient's details, so removing
  the account does not alter historical records.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, fields

from . import events, validators as v
from .database import now
from .errors import NotFound, ValidationError
from .roles import LAB_PERSONNEL, Role, User, require_role

CAN_DELETE = {Role.SPECIMEN_COLLECTOR, Role.LAB_MANAGER}


@dataclass
class Patient:
    first_name: str
    last_name: str
    date_of_birth: str              # YYYY-MM-DD
    address: str
    phone: str
    email: str = ""
    gender: str = "Unknown"
    insurance_provider: str = ""
    insurance_policy_number: str = ""
    insurance_coverage: str = ""
    patient_id: int | None = field(default=None)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def age(self) -> int:
        return v.age_on(self.date_of_birth)

    @property
    def has_insurance(self) -> bool:
        return bool(self.insurance_provider and self.insurance_policy_number)


_COLUMNS = [f.name for f in fields(Patient) if f.name != "patient_id"]
_LABELS = {
    "first_name": "First name",
    "last_name": "Last name",
    "date_of_birth": "Date of birth",
    "address": "Address",
    "phone": "Phone number",
}


def _validated(p: Patient) -> dict:
    data = {c: v.clean(getattr(p, c)) for c in _COLUMNS}
    v.required(data, _LABELS)
    data["date_of_birth"] = v.date_of_birth(data["date_of_birth"])
    data["phone"] = v.phone(data["phone"])
    data["email"] = v.email(data["email"])
    data["gender"] = data["gender"] or "Unknown"
    if data["gender"] not in v.GENDERS:
        raise ValidationError(f"Gender must be one of: {', '.join(v.GENDERS)}.")
    # Insurance is captured as a set: a provider without a policy number cannot be billed.
    if bool(data["insurance_provider"]) != bool(data["insurance_policy_number"]):
        raise ValidationError("Enter both the insurance provider and the policy number, or neither.")
    return data


def _row_to_patient(row: sqlite3.Row) -> Patient:
    return Patient(**{k: row[k] for k in _COLUMNS}, patient_id=row["patient_id"])


def create(conn: sqlite3.Connection, user: User, patient: Patient) -> Patient:
    require_role(user, LAB_PERSONNEL, "create patient accounts")
    data = _validated(patient)
    ts = now()
    cur = conn.execute(
        f"INSERT INTO patients ({', '.join(_COLUMNS)}, created_at, created_by, updated_at, updated_by)"
        f" VALUES ({', '.join(':' + c for c in _COLUMNS)}, :ts, :by, :ts, :by)",
        {**data, "ts": ts, "by": str(user)},
    )
    conn.commit()
    events.emit("patient.created", user, patient_id=cur.lastrowid)
    return get(conn, cur.lastrowid)


def update(conn: sqlite3.Connection, user: User, patient: Patient) -> Patient:
    require_role(user, LAB_PERSONNEL, "update patient accounts")
    if patient.patient_id is None:
        raise ValidationError("Select a patient to update.")
    get(conn, patient.patient_id)  # raises NotFound
    data = _validated(patient)
    conn.execute(
        f"UPDATE patients SET {', '.join(f'{c} = :{c}' for c in _COLUMNS)},"
        " updated_at = :ts, updated_by = :by WHERE patient_id = :pid",
        {**data, "ts": now(), "by": str(user), "pid": patient.patient_id},
    )
    conn.commit()
    events.emit("patient.updated", user, patient_id=patient.patient_id)
    return get(conn, patient.patient_id)


def delete(conn: sqlite3.Connection, user: User, patient_id: int) -> None:
    require_role(user, CAN_DELETE, "remove patients from the system")
    patient = get(conn, patient_id)
    open_sale = conn.execute(
        "SELECT 1 FROM purchases WHERE patient_id = ? AND status = 'OPEN'", (patient_id,)
    ).fetchone()
    if open_sale:
        raise ValidationError(
            f"{patient.full_name} has an unfinished sale at the POS. Complete or void it first."
        )
    conn.execute("DELETE FROM patients WHERE patient_id = ?", (patient_id,))
    conn.commit()
    events.emit("patient.deleted", user, patient_id=patient_id, name=patient.full_name)


def get(conn: sqlite3.Connection, patient_id: int) -> Patient:
    row = conn.execute("SELECT * FROM patients WHERE patient_id = ?", (patient_id,)).fetchone()
    if row is None:
        raise NotFound(f"Patient #{patient_id} does not exist.")
    return _row_to_patient(row)


def search(conn: sqlite3.Connection, text: str = "") -> list[Patient]:
    """Find patients by ID, name, phone, email or policy number (empty text lists everyone)."""
    text = v.clean(text).lstrip("#")
    if not text:
        rows = conn.execute("SELECT * FROM patients ORDER BY last_name, first_name").fetchall()
    elif text.isdigit() and len(text) <= 6:  # a short number is a patient ID
        rows = conn.execute("SELECT * FROM patients WHERE patient_id = ?", (int(text),)).fetchall()
    else:
        like = f"%{text}%"
        rows = conn.execute(
            "SELECT * FROM patients WHERE first_name || ' ' || last_name LIKE ?"
            " OR phone LIKE ? OR email LIKE ? OR insurance_policy_number LIKE ?"
            " ORDER BY last_name, first_name",
            (like, like, like, like),
        ).fetchall()
    return [_row_to_patient(r) for r in rows]
