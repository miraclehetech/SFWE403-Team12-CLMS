"""SRS 6.6.3 - generate and print a receipt for the entire purchase (SFWE12-20)."""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import lab_info
from .database import now
from .errors import NotFound
from .validators import cents_to_money as money

if TYPE_CHECKING:  # avoid a circular import at runtime
    from .purchases import Purchase

WIDTH = 48
DEFAULT_RECEIPT_DIR = Path.home() / ".clms" / "receipts"
METHOD_NAMES = {"CASH": "Cash", "DEBIT": "Debit", "CREDIT": "Credit"}


@dataclass
class Receipt:
    receipt_no: str
    purchase_id: int
    created_at: str
    body: str


def _row(left: str, right: str) -> str:
    space = WIDTH - len(right) - 1
    return f"{left[:space]:<{space}} {right}"


def render(lab: lab_info.LabInfo, sale: "Purchase", receipt_no: str, cashier: str) -> str:
    rule = "-" * WIDTH
    lines = [lab.name.center(WIDTH)]
    for extra in (lab.address, lab.phone, lab.website):
        if extra:
            lines.append(extra.center(WIDTH))
    lines += [
        rule,
        f"Receipt:  {receipt_no}",
        f"Date:     {sale.completed_at or now()}",
        f"Cashier:  {cashier}",
        f"Customer: {sale.customer_name}" + (f"  (Patient #{sale.patient_id})" if sale.patient_id else ""),
        rule,
    ]
    for item in sale.items:
        label = item.description if item.quantity == 1 else f"{item.description} x{item.quantity}"
        lines.append(_row(label, money(item.line_total_cents)))
        if item.quantity > 1:
            lines.append(f"    @ {money(item.unit_price_cents)} each")
    lines += [rule, _row("TOTAL", money(sale.total_cents)), ""]
    for p in sale.payments:
        name = METHOD_NAMES[p.method] + (f" ****{p.card_last4}" if p.card_last4 else "")
        shown = p.tendered_cents if p.method == "CASH" else p.amount_cents
        lines.append(_row(name, money(shown)))
        if p.reference:
            lines.append(f"    Auth ref: {p.reference}")
    lines.append(_row("CHANGE", money(sale.change_cents)))
    lines += [
        rule,
        "Customer signed for the samples taken:",
        f"  {sale.signed_by or ''}  ({sale.signed_at or ''})",
        "",
        "Signature: ______________________________",
        rule,
        "Thank you. Results are released to you and",
        "your ordering physician once validated.",
    ]
    return "\n".join(lines) + "\n"


def create(conn: sqlite3.Connection, sale: "Purchase", cashier: str) -> Receipt:
    """Build and store the receipt. Called by ``purchases.complete`` inside its transaction."""
    receipt_no = f"R{(sale.completed_at or now())[:10].replace('-', '')}-{sale.purchase_id:06d}"
    body = render(lab_info.get(conn), sale, receipt_no, cashier)
    created = now()
    conn.execute(
        "INSERT INTO receipts (receipt_no, purchase_id, created_at, body) VALUES (?, ?, ?, ?)",
        (receipt_no, sale.purchase_id, created, body),
    )
    return Receipt(receipt_no, sale.purchase_id, created, body)


def get(conn: sqlite3.Connection, purchase_id: int) -> Receipt:
    row = conn.execute("SELECT * FROM receipts WHERE purchase_id = ?", (purchase_id,)).fetchone()
    if row is None:
        raise NotFound(f"Sale #{purchase_id} has no receipt.")
    return Receipt(**dict(row))


def save(receipt: Receipt, folder: str | Path = DEFAULT_RECEIPT_DIR) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{receipt.receipt_no}.txt"
    path.write_text(receipt.body, encoding="utf-8")
    return path


def print_receipt(receipt: Receipt, folder: str | Path = DEFAULT_RECEIPT_DIR) -> tuple[Path, bool]:
    """Save the receipt and send it to the default printer.

    Returns ``(path, sent)``. ``sent`` is False when no printer command is
    available; the saved file can then be printed by hand.
    """
    path = save(receipt, folder)
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path), "print")  # type: ignore[attr-defined]
            return path, True
        for cmd in ("lp", "lpr"):
            if shutil.which(cmd):
                subprocess.run([cmd, str(path)], check=True, capture_output=True, timeout=30)
                return path, True
    except (OSError, subprocess.SubprocessError):
        pass
    return path, False
