"""SRS 6.1.1 - store basic laboratory information (SFWE12-2).

Everyone can view the information; only the laboratory manager can change it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass

from . import events, validators as v
from .database import now
from .roles import Role, User, require_role


@dataclass
class LabInfo:
    name: str
    website: str = ""
    address: str = ""
    owner: str = ""
    phone: str = ""
    working_hours: str = ""


FIELDS = ("name", "website", "address", "owner", "phone", "working_hours")
LABELS = {
    "name": "Laboratory name",
    "website": "Website",
    "address": "Address",
    "owner": "Owner",
    "phone": "Phone number",
    "working_hours": "Working hours",
}


def get(conn: sqlite3.Connection) -> LabInfo:
    row = conn.execute(f"SELECT {', '.join(FIELDS)} FROM lab_info WHERE id = 1").fetchone()
    return LabInfo(**dict(row))


def update(conn: sqlite3.Connection, user: User, info: LabInfo) -> LabInfo:
    require_role(user, {Role.LAB_MANAGER}, "change the laboratory information")
    data = {k: v.clean(val) for k, val in asdict(info).items()}
    v.required(data, LABELS)  # SRS 6.1.1 lists all six as information the lab stores
    data["phone"] = v.phone(data["phone"])
    data["website"] = v.website(data["website"])
    conn.execute(
        "UPDATE lab_info SET name=:name, website=:website, address=:address, owner=:owner,"
        " phone=:phone, working_hours=:working_hours, updated_at=:ts, updated_by=:by WHERE id = 1",
        {**data, "ts": now(), "by": str(user)},
    )
    conn.commit()
    events.emit("lab_info.updated", user, **data)
    return LabInfo(**data)
