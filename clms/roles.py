"""User types (SRS 6.1.3) and the signed-in user.

Account creation, login and authentication belong to SFWE12-5/SFWE12-6.
This module only defines the roles and a small ``User`` value object so the
features in this package can enforce role-based permissions. When the login
module is ready it should produce a ``User`` and hand it to the GUI.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .errors import PermissionDenied


class Role(str, Enum):
    LAB_MANAGER = "Laboratory Manager"
    SPECIMEN_COLLECTOR = "Specimen Collector"
    LAB_TECHNICIAN = "Laboratory Technician"
    CASHIER = "Cashier"
    PATIENT = "Patient"
    HEALTHCARE_PROVIDER = "Healthcare Provider"


#: Everyone who works at the laboratory ("laboratory personnel" / "laboratory staff" in the SRS).
LAB_PERSONNEL = frozenset(
    {Role.LAB_MANAGER, Role.SPECIMEN_COLLECTOR, Role.LAB_TECHNICIAN, Role.CASHIER}
)


@dataclass(frozen=True)
class User:
    username: str
    display_name: str
    role: Role

    @property
    def is_lab_personnel(self) -> bool:
        return self.role in LAB_PERSONNEL

    def __str__(self) -> str:  # used on receipts and in "entered by" columns
        return f"{self.display_name} ({self.role.value})"


def require_role(user: User | None, allowed, action: str) -> None:
    """Raise :class:`PermissionDenied` unless ``user`` has one of the ``allowed`` roles."""
    if user is None:
        raise PermissionDenied(f"You must be signed in to {action}.")
    allowed = frozenset(allowed)
    if user.role not in allowed:
        names = ", ".join(sorted(r.value for r in allowed))
        raise PermissionDenied(
            f"A {user.role.value} cannot {action}. Allowed roles: {names}."
        )


#: Demo accounts used by the GUI until SFWE12-5/6 (staff accounts + login) are merged.
DEMO_USERS = (
    User("manager", "Morgan Lee", Role.LAB_MANAGER),
    User("collector", "Sam Rivera", Role.SPECIMEN_COLLECTOR),
    User("tech", "Taylor Chen", Role.LAB_TECHNICIAN),
    User("cashier", "Casey Brooks", Role.CASHIER),
)
