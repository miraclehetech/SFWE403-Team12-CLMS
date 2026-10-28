"""SRS 6.6 - test purchases and point-of-sale checkout (SFWE12-19, SFWE12-20).

Typical flow at the counter::

    sale = purchases.start(conn, user, patient_id=7)            # 6.6.1
    purchases.add_test_request(conn, user, sale.purchase_id, "RPT-...")
    purchases.add_item(conn, user, sale.purchase_id, "UA")      # manual entry from the GUI
    purchases.add_payment(conn, user, sale.purchase_id, "CREDIT", 50.00, card_number="4111...")  # 6.6.4
    purchases.add_payment(conn, user, sale.purchase_id, "CASH", 20.00, tendered=40.00)
    purchases.record_signature(conn, user, sale.purchase_id, "Jane Doe")   # 6.6.2
    receipt = purchases.complete(conn, user, sale.purchase_id)              # 6.6.3

Card payments are recorded, not charged: the SRS does not define a card
processor, so a simulated authorization reference is stored and only the last
four digits of the card number are kept.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import dataclass, field

from . import events, lab_tests, patients, receipts, validators as v
from .database import now
from .errors import InvalidState, NotFound, ValidationError
from .roles import LAB_PERSONNEL, User, require_role

METHODS = {"CASH": "Cash", "DEBIT": "Debit card", "CREDIT": "Credit card"}
MAX_QUANTITY = 20


@dataclass
class PurchaseItem:
    item_id: int
    test_code: str
    description: str
    unit_price_cents: int
    quantity: int
    report_id: str | None

    @property
    def line_total_cents(self) -> int:
        return self.unit_price_cents * self.quantity


@dataclass
class Payment:
    payment_id: int
    method: str
    amount_cents: int       # applied to the sale
    tendered_cents: int     # handed over (cash may exceed the amount -> change)
    card_last4: str | None
    reference: str | None
    created_at: str

    @property
    def change_cents(self) -> int:
        return self.tendered_cents - self.amount_cents


@dataclass
class Purchase:
    purchase_id: int
    patient_id: int | None
    customer_name: str
    status: str
    created_at: str
    created_by: str
    signature_obtained: bool
    signed_by: str | None
    signed_at: str | None
    completed_at: str | None
    items: list[PurchaseItem] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)

    @property
    def total_cents(self) -> int:
        return sum(i.line_total_cents for i in self.items)

    @property
    def paid_cents(self) -> int:
        return sum(p.amount_cents for p in self.payments)

    @property
    def balance_cents(self) -> int:
        return self.total_cents - self.paid_cents

    @property
    def change_cents(self) -> int:
        return sum(p.change_cents for p in self.payments)

    @property
    def is_open(self) -> bool:
        return self.status == "OPEN"


# ---------------------------------------------------------------- helpers

def _require_staff(user: User, action: str) -> None:
    require_role(user, LAB_PERSONNEL, action)


def _open(conn: sqlite3.Connection, purchase_id: int) -> Purchase:
    sale = get(conn, purchase_id)
    if not sale.is_open:
        raise InvalidState(f"Sale #{purchase_id} is {sale.status.lower()} and can no longer be changed.")
    return sale


def _amount(value, label: str = "Amount") -> int:
    """Dollar amount (int, float or text such as "12.50") -> cents."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        cents = round(value * 100)
    else:
        cents = v.money_to_cents(value)
    if cents <= 0:
        raise ValidationError(f"{label} must be greater than $0.00.")
    return cents


def luhn_ok(number: str) -> bool:
    digits = [int(d) for d in number][::-1]
    total = sum(digits[0::2]) + sum(sum(divmod(2 * d, 10)) for d in digits[1::2])
    return total % 10 == 0


# ---------------------------------------------------------------- SFWE12-19: build the sale

def start(
    conn: sqlite3.Connection, user: User, *, patient_id: int | None = None, customer_name: str = ""
) -> Purchase:
    """Open a new sale for a registered patient (preferred) or a named walk-in customer."""
    _require_staff(user, "process test purchases")
    if patient_id is not None:
        customer_name = patients.get(conn, patient_id).full_name
    customer_name = v.clean(customer_name)
    if not customer_name:
        raise ValidationError("Select a patient or enter the customer's name.")
    cur = conn.execute(
        "INSERT INTO purchases (patient_id, customer_name, created_at, created_by) VALUES (?, ?, ?, ?)",
        (patient_id, customer_name, now(), str(user)),
    )
    conn.commit()
    events.emit("purchase.started", user, purchase_id=cur.lastrowid)
    return get(conn, cur.lastrowid)


def add_item(
    conn: sqlite3.Connection, user: User, purchase_id: int, test_code: str, quantity: int = 1
) -> Purchase:
    """Manually add a test from the catalog (SRS 6.6.1). Adding the same test again raises the quantity."""
    _require_staff(user, "process test purchases")
    sale = _open(conn, purchase_id)
    test = lab_tests.get_catalog_test(conn, test_code)
    if not test.active:
        raise ValidationError(f"{test.test_name} is no longer offered.")
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise ValidationError("Quantity must be a whole number.") from None
    existing = next((i for i in sale.items if i.test_code == test.test_code and i.report_id is None), None)
    new_qty = quantity + (existing.quantity if existing else 0)
    if not 1 <= new_qty <= MAX_QUANTITY:
        raise ValidationError(f"Quantity must be between 1 and {MAX_QUANTITY}.")
    if existing:
        conn.execute("UPDATE purchase_items SET quantity = ? WHERE item_id = ?", (new_qty, existing.item_id))
    else:
        conn.execute(
            "INSERT INTO purchase_items (purchase_id, test_code, description, unit_price_cents, quantity)"
            " VALUES (?, ?, ?, ?, ?)",
            (purchase_id, test.test_code, test.test_name, test.price_cents, quantity),
        )
    conn.commit()
    events.emit("purchase.item_added", user, purchase_id=purchase_id, test_code=test.test_code)
    return get(conn, purchase_id)


def add_test_request(conn: sqlite3.Connection, user: User, purchase_id: int, report_id: str) -> Purchase:
    """Bill a test request that was accepted at intake (links the line to the report)."""
    _require_staff(user, "process test purchases")
    sale = _open(conn, purchase_id)
    req = lab_tests.get(conn, report_id)
    if sale.patient_id is None or req.patient_id != sale.patient_id:
        raise ValidationError(f"{report_id} belongs to a different patient.")
    if req.report_id not in {r.report_id for r in lab_tests.unbilled_requests(conn, sale.patient_id)}:
        raise ValidationError(f"{report_id} is already on another sale.")
    price = lab_tests.get_catalog_test(conn, req.test_code).price_cents
    conn.execute(
        "INSERT INTO purchase_items (purchase_id, test_code, description, unit_price_cents, quantity, report_id)"
        " VALUES (?, ?, ?, ?, 1, ?)",
        (purchase_id, req.test_code, f"{req.test_name} ({req.report_id})", price, req.report_id),
    )
    conn.commit()
    events.emit("purchase.item_added", user, purchase_id=purchase_id, report_id=report_id)
    return get(conn, purchase_id)


def remove_item(conn: sqlite3.Connection, user: User, purchase_id: int, item_id: int) -> Purchase:
    _require_staff(user, "process test purchases")
    sale = _open(conn, purchase_id)
    if sale.payments:
        raise InvalidState("Remove the recorded payments before changing the items.")
    if conn.execute(
        "DELETE FROM purchase_items WHERE item_id = ? AND purchase_id = ?", (item_id, purchase_id)
    ).rowcount == 0:
        raise NotFound("That item is not on this sale.")
    conn.commit()
    return get(conn, purchase_id)


# ---------------------------------------------------------------- SFWE12-20: POS checkout

def add_payment(
    conn: sqlite3.Connection,
    user: User,
    purchase_id: int,
    method: str,
    amount,
    *,
    tendered=None,
    card_number: str | None = None,
) -> Purchase:
    """Record a cash, debit or credit payment (SRS 6.6.4). Several payments may be combined.

    * Cash: ``tendered`` is what the customer hands over (defaults to ``amount``);
      anything above the remaining balance is returned as change.
    * Debit/credit: ``amount`` cannot exceed the balance; the card number is checked
      and only its last four digits are stored.
    """
    _require_staff(user, "take payments")
    method = v.clean(method).upper()
    if method not in METHODS:
        raise ValidationError("Payment method must be cash, debit or credit.")
    sale = _open(conn, purchase_id)
    if not sale.items:
        raise InvalidState("Add at least one test before taking payment.")
    balance = sale.balance_cents
    if balance <= 0:
        raise InvalidState("This sale is already paid in full.")

    amount_c = _amount(amount)
    last4 = reference = None
    if method == "CASH":
        tendered_c = _amount(tendered, "Cash tendered") if tendered not in (None, "") else amount_c
        if tendered_c < amount_c:
            raise ValidationError("Cash tendered is less than the amount being paid.")
        applied = min(amount_c, balance)
        # change = everything handed over beyond what is applied to the balance
    else:
        if amount_c > balance:
            raise ValidationError(
                f"Card amount {v.cents_to_money(amount_c)} is more than the balance {v.cents_to_money(balance)}."
            )
        digits = re.sub(r"[\s-]", "", v.clean(card_number))
        if not re.fullmatch(r"\d{13,19}", digits) or not luhn_ok(digits):
            raise ValidationError("Card number is not valid.")
        applied = tendered_c = amount_c
        last4 = digits[-4:]
        reference = "SIM-" + uuid.uuid4().hex[:10].upper()

    conn.execute(
        "INSERT INTO payments (purchase_id, method, amount_cents, tendered_cents, card_last4, reference, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (purchase_id, method, applied, tendered_c, last4, reference, now()),
    )
    conn.commit()
    events.emit("purchase.payment", user, purchase_id=purchase_id, method=method, amount_cents=applied)
    return get(conn, purchase_id)


def remove_payment(conn: sqlite3.Connection, user: User, purchase_id: int, payment_id: int) -> Purchase:
    """Undo a payment entered by mistake (only while the sale is open)."""
    _require_staff(user, "take payments")
    _open(conn, purchase_id)
    if conn.execute(
        "DELETE FROM payments WHERE payment_id = ? AND purchase_id = ?", (payment_id, purchase_id)
    ).rowcount == 0:
        raise NotFound("That payment is not on this sale.")
    conn.commit()
    events.emit("purchase.payment_removed", user, purchase_id=purchase_id, payment_id=payment_id)
    return get(conn, purchase_id)


def record_signature(conn: sqlite3.Connection, user: User, purchase_id: int, signed_by: str) -> Purchase:
    """Confirm the customer signed for the samples taken (SRS 6.6.2 - paper signature is fine)."""
    _require_staff(user, "record customer signatures")
    _open(conn, purchase_id)
    signed_by = v.clean(signed_by)
    if not signed_by:
        raise ValidationError("Enter the name of the person who signed.")
    conn.execute(
        "UPDATE purchases SET signature_obtained = 1, signed_by = ?, signed_at = ? WHERE purchase_id = ?",
        (signed_by, now(), purchase_id),
    )
    conn.commit()
    events.emit("purchase.signed", user, purchase_id=purchase_id)
    return get(conn, purchase_id)


def complete(conn: sqlite3.Connection, user: User, purchase_id: int) -> receipts.Receipt:
    """Finish the sale and generate its receipt (SRS 6.6.3)."""
    _require_staff(user, "complete sales")
    sale = _open(conn, purchase_id)
    problems = []
    if not sale.items:
        problems.append("add at least one test")
    if sale.balance_cents > 0:
        problems.append(f"collect the remaining {v.cents_to_money(sale.balance_cents)}")
    if not sale.signature_obtained:
        problems.append("get the customer's signature for the samples taken")
    if problems:
        raise InvalidState("Before completing the sale: " + "; ".join(problems) + ".")
    with conn:
        conn.execute(
            "UPDATE purchases SET status = 'COMPLETED', completed_at = ?, total_cents = ?, change_cents = ?"
            " WHERE purchase_id = ?",
            (now(), sale.total_cents, sale.change_cents, purchase_id),
        )
        receipt = receipts.create(conn, get(conn, purchase_id), cashier=str(user))
    events.emit("purchase.completed", user, purchase_id=purchase_id, total_cents=sale.total_cents)
    return receipt


def void(conn: sqlite3.Connection, user: User, purchase_id: int) -> Purchase:
    """Cancel an unfinished sale. Its test requests become available to bill again."""
    _require_staff(user, "void sales")
    _open(conn, purchase_id)
    conn.execute("UPDATE purchases SET status = 'VOID' WHERE purchase_id = ?", (purchase_id,))
    conn.commit()
    events.emit("purchase.voided", user, purchase_id=purchase_id)
    return get(conn, purchase_id)


# ---------------------------------------------------------------- queries

def get(conn: sqlite3.Connection, purchase_id: int) -> Purchase:
    row = conn.execute("SELECT * FROM purchases WHERE purchase_id = ?", (purchase_id,)).fetchone()
    if row is None:
        raise NotFound(f"Sale #{purchase_id} does not exist.")
    items = [
        PurchaseItem(**dict(r))
        for r in conn.execute(
            "SELECT item_id, test_code, description, unit_price_cents, quantity, report_id"
            " FROM purchase_items WHERE purchase_id = ? ORDER BY item_id",
            (purchase_id,),
        )
    ]
    pays = [
        Payment(**dict(r))
        for r in conn.execute(
            "SELECT payment_id, method, amount_cents, tendered_cents, card_last4, reference, created_at"
            " FROM payments WHERE purchase_id = ? ORDER BY payment_id",
            (purchase_id,),
        )
    ]
    data = dict(row)
    data.pop("total_cents")
    data.pop("change_cents")
    data["signature_obtained"] = bool(data["signature_obtained"])
    return Purchase(**data, items=items, payments=pays)


def list_purchases(conn: sqlite3.Connection, status: str | None = None) -> list[Purchase]:
    sql, args = "SELECT purchase_id FROM purchases", ()
    if status:
        sql, args = sql + " WHERE status = ?", (status,)
    return [get(conn, r[0]) for r in conn.execute(sql + " ORDER BY purchase_id DESC", args)]
