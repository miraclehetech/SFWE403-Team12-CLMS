"""SRS 6.3.1 / 6.3.2 - accept test requests and capture every required field (SFWE12-7).

Two intake channels:

* ``WALK_IN`` - the patient brings the order to the laboratory (6.3.1).
* ``PHONE``   - a doctor's office phones the order in (6.3.2).

Per the note added on Oct 1st every test carries: report information,
patient information, ordering physician information, test execution details,
test results and health insurance / billing. Intake fills in what is known at
ordering time; the rest is completed as the sample moves through the lab:

    pending  --record_collection-->  pending (sample collected)
             --record_result----->   completed
             --validate_result--->   validated
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from . import events, patients, validators as v
from .database import now
from .errors import InvalidState, NotFound, ValidationError
from .roles import LAB_PERSONNEL, Role, User, require_role

SOURCES = {"WALK_IN": "Walk-in (patient brought order)", "PHONE": "Phoned in by doctor's office"}
STATUSES = ("pending", "completed", "validated")

CAN_COLLECT = {Role.SPECIMEN_COLLECTOR, Role.LAB_MANAGER}
CAN_RECORD_RESULT = {Role.LAB_TECHNICIAN, Role.LAB_MANAGER}
CAN_VALIDATE = {Role.LAB_MANAGER}


@dataclass
class CatalogTest:
    test_code: str
    test_name: str
    sample_type: str
    units: str
    reference_range: str
    price_cents: int
    active: int = 1

    def __str__(self) -> str:
        return f"{self.test_code} - {self.test_name}"


@dataclass
class Physician:
    physician_id: str     # license number / provider ID
    name: str
    phone: str = ""
    email: str = ""
    practice: str = ""


@dataclass
class TestRequest:
    report_id: str
    report_datetime: str
    source: str
    entered_by: str
    patient_id: int | None
    patient_name: str
    patient_dob: str
    patient_gender: str
    physician_id: str
    physician_name: str
    test_code: str
    sample_type: str
    sample_id: str | None
    collection_datetime: str | None
    collected_by: str | None
    performed_by: str | None
    machine_used: str | None
    test_name: str
    result_value: str | None
    result_units: str
    reference_range: str
    result_status: str
    results_received_datetime: str | None
    validated_by: str | None
    insurance_provider: str
    insurance_policy_number: str
    notes: str

    @property
    def patient_age(self) -> int:
        return v.age_on(self.patient_dob)

    @property
    def is_collected(self) -> bool:
        return bool(self.sample_id and self.collection_datetime)


# ---------------------------------------------------------------- catalog / physicians

def list_catalog(conn: sqlite3.Connection, active_only: bool = True) -> list[CatalogTest]:
    sql = "SELECT * FROM test_catalog" + (" WHERE active = 1" if active_only else "") + " ORDER BY test_name"
    return [CatalogTest(**dict(r)) for r in conn.execute(sql)]


def get_catalog_test(conn: sqlite3.Connection, test_code: str) -> CatalogTest:
    row = conn.execute("SELECT * FROM test_catalog WHERE test_code = ?", (v.clean(test_code),)).fetchone()
    if row is None:
        raise NotFound(f"Test '{test_code}' is not in the catalog.")
    return CatalogTest(**dict(row))


def get_physician(conn: sqlite3.Connection, physician_id: str) -> Physician | None:
    row = conn.execute("SELECT * FROM physicians WHERE physician_id = ?", (v.clean(physician_id),)).fetchone()
    return Physician(**dict(row)) if row else None


def list_physicians(conn: sqlite3.Connection) -> list[Physician]:
    return [Physician(**dict(r)) for r in conn.execute("SELECT * FROM physicians ORDER BY name")]


def _save_physician(conn: sqlite3.Connection, doc: Physician) -> Physician:
    data = {
        "physician_id": v.clean(doc.physician_id).upper(),
        "name": v.clean(doc.name),
        "phone": v.clean(doc.phone),
        "email": v.clean(doc.email),
        "practice": v.clean(doc.practice),
    }
    v.required(data, {"physician_id": "Physician ID / license", "name": "Physician name"})
    if not data["phone"] and not data["email"]:
        raise ValidationError("Enter the ordering physician's phone number or email (contact details are required).")
    if data["phone"]:
        data["phone"] = v.phone(data["phone"], "Physician phone")
    data["email"] = v.email(data["email"])
    conn.execute(
        "INSERT INTO physicians (physician_id, name, phone, email, practice)"
        " VALUES (:physician_id, :name, :phone, :email, :practice)"
        " ON CONFLICT(physician_id) DO UPDATE SET name = excluded.name, phone = excluded.phone,"
        " email = excluded.email, practice = excluded.practice",
        data,
    )
    return Physician(**data)


# ---------------------------------------------------------------- intake

def _next_report_id(conn: sqlite3.Connection) -> str:
    prefix = "RPT-" + datetime.now().strftime("%Y%m%d") + "-"
    row = conn.execute(
        "SELECT report_id FROM test_requests WHERE report_id LIKE ? ORDER BY report_id DESC LIMIT 1",
        (prefix + "%",),
    ).fetchone()
    seq = int(row[0].rsplit("-", 1)[1]) + 1 if row else 1
    return f"{prefix}{seq:04d}"


def accept_test(
    conn: sqlite3.Connection,
    user: User,
    *,
    source: str,
    patient_id: int,
    physician: Physician,
    test_code: str,
    insurance_provider: str | None = None,
    insurance_policy_number: str | None = None,
    notes: str = "",
) -> TestRequest:
    """Register a new test request.

    Insurance defaults to what is on the patient's account; pass values to override
    (for example a new card presented at the desk).
    """
    if source not in SOURCES:
        raise ValidationError("Choose how the test request was received.")
    action = "accept walk-in test requests" if source == "WALK_IN" else "enter phoned-in test requests"
    require_role(user, LAB_PERSONNEL, action)

    patient = patients.get(conn, patient_id)
    test = get_catalog_test(conn, test_code)
    if not test.active:
        raise ValidationError(f"{test.test_name} is no longer offered.")

    provider = v.clean(insurance_provider) or patient.insurance_provider
    policy = v.clean(insurance_policy_number) or patient.insurance_policy_number
    if not provider or not policy:
        raise ValidationError(
            "Every test request needs the patient's insurance provider and policy number."
        )

    with conn:  # one transaction: physician + request
        doc = _save_physician(conn, physician)
        report_id = _next_report_id(conn)
        conn.execute(
            "INSERT INTO test_requests (report_id, report_datetime, source, entered_by,"
            " patient_id, patient_name, patient_dob, patient_gender, physician_id, physician_name,"
            " test_code, sample_type, test_name, result_units, reference_range, result_status,"
            " insurance_provider, insurance_policy_number, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (
                report_id, now(), source, str(user),
                patient.patient_id, patient.full_name, patient.date_of_birth, patient.gender,
                doc.physician_id, doc.name,
                test.test_code, test.sample_type, test.test_name, test.units, test.reference_range,
                provider, policy, v.clean(notes),
            ),
        )
    events.emit("test.accepted", user, report_id=report_id, source=source, patient_id=patient_id)
    return get(conn, report_id)


# ---------------------------------------------------------------- lifecycle

def record_collection(
    conn: sqlite3.Connection,
    user: User,
    report_id: str,
    *,
    sample_id: str,
    collected_by: str,
    collection_datetime: str | None = None,
) -> TestRequest:
    """Store the sample ID (barcode), who collected it and when."""
    require_role(user, CAN_COLLECT, "record sample collection")
    req = get(conn, report_id)
    if req.result_status != "pending":
        raise InvalidState(f"{report_id} already has results; the collection can no longer change.")
    sample_id = v.clean(sample_id)
    collected_by = v.clean(collected_by)
    v.required({"s": sample_id, "c": collected_by}, {"s": "Sample ID", "c": "Collected by"})
    clash = conn.execute(
        "SELECT report_id FROM test_requests WHERE sample_id = ? AND report_id <> ?", (sample_id, report_id)
    ).fetchone()
    if clash:
        raise ValidationError(f"Sample ID {sample_id} is already used by {clash[0]}.")
    when = v.parse_datetime(collection_datetime, "Collection date & time") if collection_datetime else now()
    conn.execute(
        "UPDATE test_requests SET sample_id = ?, collected_by = ?, collection_datetime = ? WHERE report_id = ?",
        (sample_id, collected_by, when, report_id),
    )
    conn.commit()
    events.emit("test.collected", user, report_id=report_id, sample_id=sample_id)
    return get(conn, report_id)


def record_result(
    conn: sqlite3.Connection,
    user: User,
    report_id: str,
    *,
    result_value: str,
    performed_by: str,
    machine_used: str,
    result_units: str | None = None,
    results_received_datetime: str | None = None,
) -> TestRequest:
    """Enter the result (quantitative or qualitative); status becomes ``completed``.

    The automatic import of analyzer ``.txt`` files is SFWE12-10; it can call this function.
    """
    require_role(user, CAN_RECORD_RESULT, "record test results")
    req = get(conn, report_id)
    if req.result_status == "validated":
        raise InvalidState(f"{report_id} is already validated and cannot be changed.")
    if not req.is_collected:
        raise InvalidState(f"Record the sample collection for {report_id} before entering results.")
    data = {"r": v.clean(result_value), "p": v.clean(performed_by), "m": v.clean(machine_used)}
    v.required(data, {"r": "Result value", "p": "Test performed by", "m": "Machine / instrument used"})
    received = (
        v.parse_datetime(results_received_datetime, "Results received date & time")
        if results_received_datetime else now()
    )
    units = req.result_units if result_units is None else v.clean(result_units)
    conn.execute(
        "UPDATE test_requests SET result_value = ?, performed_by = ?, machine_used = ?, result_units = ?,"
        " results_received_datetime = ?, result_status = 'completed' WHERE report_id = ?",
        (data["r"], data["p"], data["m"], units, received, report_id),
    )
    conn.commit()
    events.emit("test.completed", user, report_id=report_id)
    return get(conn, report_id)


def validate_result(conn: sqlite3.Connection, user: User, report_id: str) -> TestRequest:
    """Second-level approval of a completed result; status becomes ``validated``."""
    require_role(user, CAN_VALIDATE, "validate test results")
    req = get(conn, report_id)
    if req.result_status != "completed":
        raise InvalidState(f"Only completed results can be validated ({report_id} is {req.result_status}).")
    conn.execute(
        "UPDATE test_requests SET result_status = 'validated', validated_by = ? WHERE report_id = ?",
        (str(user), report_id),
    )
    conn.commit()
    events.emit("test.validated", user, report_id=report_id)
    return get(conn, report_id)


# ---------------------------------------------------------------- queries

def get(conn: sqlite3.Connection, report_id: str) -> TestRequest:
    row = conn.execute("SELECT * FROM test_requests WHERE report_id = ?", (v.clean(report_id),)).fetchone()
    if row is None:
        raise NotFound(f"Test report {report_id} does not exist.")
    return TestRequest(**dict(row))


def list_requests(
    conn: sqlite3.Connection, *, patient_id: int | None = None, status: str | None = None
) -> list[TestRequest]:
    sql, args = "SELECT * FROM test_requests WHERE 1 = 1", []
    if patient_id is not None:
        sql += " AND patient_id = ?"
        args.append(patient_id)
    if status:
        sql += " AND result_status = ?"
        args.append(status)
    sql += " ORDER BY report_id DESC"
    return [TestRequest(**dict(r)) for r in conn.execute(sql, args)]


def unbilled_requests(conn: sqlite3.Connection, patient_id: int) -> list[TestRequest]:
    """Requests for this patient that are not yet on an open or completed purchase."""
    rows = conn.execute(
        "SELECT t.* FROM test_requests t WHERE t.patient_id = ? AND NOT EXISTS ("
        "  SELECT 1 FROM purchase_items i JOIN purchases p ON p.purchase_id = i.purchase_id"
        "  WHERE i.report_id = t.report_id AND p.status <> 'VOID') ORDER BY t.report_id",
        (patient_id,),
    ).fetchall()
    return [TestRequest(**dict(r)) for r in rows]
