"""Small input checks shared by the service modules."""

from __future__ import annotations

import re
from datetime import date, datetime

from .errors import ValidationError

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL = re.compile(r"^(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?$", re.IGNORECASE)

GENDERS = ("Female", "Male", "Other", "Unknown")


def clean(value) -> str:
    return "" if value is None else str(value).strip()


def required(fields: dict, labels: dict) -> None:
    """Raise one error listing every empty required field (labels: key -> human name)."""
    missing = [labels[k] for k in labels if not clean(fields.get(k))]
    if missing:
        raise ValidationError("Required: " + ", ".join(missing) + ".")


def phone(value: str, label: str = "Phone number") -> str:
    value = clean(value)
    digits = re.sub(r"\D", "", value)
    if not 10 <= len(digits) <= 15:
        raise ValidationError(f"{label} must contain 10-15 digits.")
    return value


def email(value: str, *, optional: bool = True) -> str:
    value = clean(value)
    if not value and optional:
        return ""
    if not _EMAIL.match(value):
        raise ValidationError("Email address is not valid.")
    return value


def website(value: str) -> str:
    value = clean(value)
    if value and not _URL.match(value):
        raise ValidationError("Website is not a valid address.")
    return value


def parse_date(value: str, label: str) -> date:
    try:
        return datetime.strptime(clean(value), "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError(f"{label} must be a date in the form YYYY-MM-DD.") from None


def date_of_birth(value: str) -> str:
    dob = parse_date(value, "Date of birth")
    if dob > date.today():
        raise ValidationError("Date of birth cannot be in the future.")
    if dob.year < 1900:
        raise ValidationError("Date of birth is before 1900.")
    return dob.isoformat()


def parse_datetime(value: str, label: str) -> str:
    """Accept ``YYYY-MM-DD HH:MM`` (or the HL7-style ``YYYYMMDDHHMM``) and normalise it."""
    value = clean(value)
    for fmt in ("%Y-%m-%d %H:%M", "%Y%m%d%H%M"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
    raise ValidationError(f"{label} must be in the form YYYY-MM-DD HH:MM.")


def age_on(dob_iso: str, on: date | None = None) -> int:
    dob = date.fromisoformat(dob_iso)
    on = on or date.today()
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def money_to_cents(value) -> int:
    """Parse a dollar amount such as ``"12"``, ``"12.5"`` or ``"$1,234.56"``."""
    text = clean(value).replace("$", "").replace(",", "")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", text):
        raise ValidationError(f"'{value}' is not a valid dollar amount.")
    dollars, _, cents = text.partition(".")
    return int(dollars) * 100 + int((cents + "00")[:2])


def cents_to_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"
