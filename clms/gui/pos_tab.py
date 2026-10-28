"""Test purchases and point of sale (SRS 6.6.1 - 6.6.4)."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import lab_tests as tr, patients, purchases as pos, receipts
from ..validators import cents_to_money as money
from .common import PAD, Table, run, set_status


class POSTab(ttk.Frame):
    title = "Point of Sale"

    def __init__(self, master, app):
        super().__init__(master, padding=12)
        self.app = app
        self.sale: pos.Purchase | None = None
        self._patients: dict[str, patients.Patient] = {}
        self._tests: dict[str, tr.CatalogTest] = {}

        # ---------------------------------------------------------- customer
        top = ttk.LabelFrame(self, text="Customer", padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="Patient:").pack(side="left", **PAD)
        self.patient_var = tk.StringVar()
        self.patient_box = ttk.Combobox(top, textvariable=self.patient_var, state="readonly", width=40)
        self.patient_box.pack(side="left", **PAD)
        ttk.Label(top, text="or walk-in name:").pack(side="left", **PAD)
        self.walk_in = tk.StringVar()
        ttk.Entry(top, textvariable=self.walk_in, width=22).pack(side="left", **PAD)
        ttk.Button(top, text="Start sale", command=self.start).pack(side="left", **PAD)

        head = ttk.Frame(self)
        head.pack(fill="x", pady=(6, 0))
        self.sale_label = ttk.Label(head, text="No sale in progress", style="Heading.TLabel")
        self.sale_label.pack(side="left")
        ttk.Button(head, text="Void sale", command=self.void).pack(side="right", **PAD)
        ttk.Button(head, text="Complete sale & print receipt", command=self.complete).pack(side="right", **PAD)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, pady=(4, 0))

        # ---------------------------------------------------------- items (6.6.1)
        left = ttk.LabelFrame(body, text="Tests being purchased", padding=6)
        left.pack(side="left", fill="both", expand=True)
        add = ttk.Frame(left)
        add.pack(fill="x")
        self.test_var = tk.StringVar()
        self.test_box = ttk.Combobox(add, textvariable=self.test_var, state="readonly", width=34)
        self.test_box.pack(side="left", **PAD)
        ttk.Label(add, text="Qty:").pack(side="left")
        self.qty = tk.StringVar(value="1")
        ttk.Spinbox(add, from_=1, to=pos.MAX_QUANTITY, textvariable=self.qty, width=4).pack(side="left", **PAD)
        ttk.Button(add, text="Add test", command=self.add_item).pack(side="left", **PAD)
        ttk.Button(left, text="Add this patient's accepted test requests", command=self.add_requests).pack(anchor="w", **PAD)
        self.items = Table(left, [("desc", "Description", 260), ("qty", "Qty", 40), ("unit", "Unit price", 80),
                                  ("line", "Amount", 80)], height=8)
        self.items.pack(fill="both", expand=True, pady=4)
        foot = ttk.Frame(left)
        foot.pack(fill="x")
        ttk.Button(foot, text="Remove item", command=self.remove_item).pack(side="left", **PAD)
        self.total_label = ttk.Label(foot, text="Total: $0.00", style="Heading.TLabel")
        self.total_label.pack(side="right", **PAD)

        # ---------------------------------------------------------- payment (6.6.4)
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", padx=(10, 0))
        pay = ttk.LabelFrame(right, text="Payment", padding=6)
        pay.pack(fill="x")
        self.method = tk.StringVar(value="Cash")
        self.amount = tk.StringVar()
        self.tendered = tk.StringVar()
        self.card = tk.StringVar()
        grid = [("Method", ttk.Combobox(pay, textvariable=self.method, values=list(pos.METHODS.values()),
                                        state="readonly", width=20)),
                ("Amount ($)", ttk.Entry(pay, textvariable=self.amount, width=22)),
                ("Cash tendered ($)", ttk.Entry(pay, textvariable=self.tendered, width=22)),
                ("Card number", ttk.Entry(pay, textvariable=self.card, width=22))]
        for r, (label, w) in enumerate(grid):
            ttk.Label(pay, text=label + ":").grid(row=r, column=0, sticky="e", **PAD)
            w.grid(row=r, column=1, sticky="we", **PAD)
        self.tendered_entry, self.card_entry = grid[2][1], grid[3][1]
        grid[0][1].bind("<<ComboboxSelected>>", lambda _e: self._method_changed())
        ttk.Button(pay, text="Add payment", command=self.add_payment).grid(row=4, column=1, sticky="e", **PAD)
        self.payments = Table(right, [("method", "Method", 110), ("amount", "Applied", 70), ("tender", "Tendered", 70)],
                              height=3)
        self.payments.pack(fill="x", pady=4)
        ttk.Button(right, text="Remove payment", command=self.remove_payment).pack(anchor="w")
        self.balance_label = ttk.Label(right, text="Balance due: $0.00   Change: $0.00")
        self.balance_label.pack(anchor="w", pady=4)

        # ---------------------------------------------------------- signature (6.6.2)
        sig = ttk.LabelFrame(right, text="Customer signature for samples taken", padding=6)
        sig.pack(fill="x", pady=(4, 0))
        ttk.Label(sig, text="Have the customer sign the paper form, then record it here.",
                  wraplength=280, foreground="#666").pack(anchor="w")
        row = ttk.Frame(sig)
        row.pack(fill="x")
        self.signer = tk.StringVar()
        ttk.Entry(row, textvariable=self.signer, width=22).pack(side="left", **PAD)
        ttk.Button(row, text="Record signature", command=self.sign).pack(side="left", **PAD)
        self.sig_label = ttk.Label(sig, text="Not signed yet", foreground="#b00")
        self.sig_label.pack(anchor="w")

        self._method_changed()
        self.show_sale()

    # ------------------------------------------------------------------ refresh
    def refresh(self):
        self._patients = {f"#{p.patient_id} - {p.full_name}": p for p in patients.search(self.app.conn)}
        self.patient_box.configure(values=["", *self._patients])
        self._tests = {f"{t.test_name} ({money(t.price_cents)})": t for t in tr.list_catalog(self.app.conn)}
        self.test_box.configure(values=list(self._tests))
        if self.sale:
            self.sale = pos.get(self.app.conn, self.sale.purchase_id)
        self.show_sale()

    def on_user_changed(self):
        pass

    def _method_changed(self):
        cash = self.method.get() == "Cash"
        self.tendered_entry.state(["!disabled"] if cash else ["disabled"])
        self.card_entry.state(["disabled"] if cash else ["!disabled"])

    def show_sale(self):
        s = self.sale
        if s is None:
            self.sale_label.configure(text="No sale in progress")
            self.items.fill([])
            self.payments.fill([])
            self.total_label.configure(text="Total: $0.00")
            self.balance_label.configure(text="Balance due: $0.00   Change: $0.00")
            self.sig_label.configure(text="Not signed yet", foreground="#b00")
            return
        self.sale_label.configure(text=f"Sale #{s.purchase_id} - {s.customer_name} [{s.status}]")
        self.items.fill((i.item_id, (i.description, i.quantity, money(i.unit_price_cents), money(i.line_total_cents)))
                        for i in s.items)
        self.payments.fill((p.payment_id, (pos.METHODS[p.method] + (f" *{p.card_last4}" if p.card_last4 else ""),
                                           money(p.amount_cents), money(p.tendered_cents)))
                           for p in s.payments)
        self.total_label.configure(text=f"Total: {money(s.total_cents)}")
        self.balance_label.configure(
            text=f"Balance due: {money(max(s.balance_cents, 0))}   Change: {money(s.change_cents)}")
        self.amount.set(f"{max(s.balance_cents, 0) / 100:.2f}" if s.balance_cents > 0 else "")
        if s.signature_obtained:
            self.sig_label.configure(text=f"Signed by {s.signed_by} at {s.signed_at}", foreground="#070")
        else:
            self.sig_label.configure(text="Not signed yet", foreground="#b00")

    def _need_sale(self) -> bool:
        if self.sale is None or not self.sale.is_open:
            messagebox.showinfo("Point of sale", "Start a sale first.", parent=self)
            return False
        return True

    def _update(self, sale):
        if sale:
            self.sale = sale
            self.show_sale()

    # ------------------------------------------------------------------ actions
    def start(self, patient_id: int | None = None):
        if patient_id is None:
            p = self._patients.get(self.patient_var.get())
            patient_id = p.patient_id if p else None
        if self.sale and self.sale.is_open and self.sale.items:
            if not messagebox.askyesno("Point of sale", f"Sale #{self.sale.purchase_id} is unfinished. "
                                       "Leave it open and start another?", parent=self):
                return
        sale = run(self, pos.start, self.app.conn, self.app.user, patient_id=patient_id,
                   customer_name=self.walk_in.get())
        if sale:
            self.signer.set(sale.customer_name)
            self.card.set("")
            self.tendered.set("")
            self._update(sale)
            set_status(self, f"Sale #{sale.purchase_id} started for {sale.customer_name}.")

    def add_item(self):
        if not self._need_sale():
            return
        test = self._tests.get(self.test_var.get())
        if not test:
            messagebox.showinfo("Point of sale", "Choose a test to add.", parent=self)
            return
        self._update(run(self, pos.add_item, self.app.conn, self.app.user, self.sale.purchase_id,
                         test.test_code, self.qty.get()))

    def add_requests(self):
        if not self._need_sale():
            return
        if self.sale.patient_id is None:
            messagebox.showinfo("Point of sale", "This sale is for a walk-in customer without a patient account.",
                                parent=self)
            return
        pending = tr.unbilled_requests(self.app.conn, self.sale.patient_id)
        if not pending:
            messagebox.showinfo("Point of sale", "This patient has no unbilled test requests.", parent=self)
            return
        for req in pending:
            self._update(run(self, pos.add_test_request, self.app.conn, self.app.user, self.sale.purchase_id,
                             req.report_id))

    def remove_item(self):
        iid = self.items.selected()
        if self._need_sale() and iid:
            self._update(run(self, pos.remove_item, self.app.conn, self.app.user, self.sale.purchase_id, int(iid)))

    def add_payment(self):
        if not self._need_sale():
            return
        method = {v: k for k, v in pos.METHODS.items()}[self.method.get()]
        sale = run(self, pos.add_payment, self.app.conn, self.app.user, self.sale.purchase_id, method,
                   self.amount.get(), tendered=self.tendered.get() or None, card_number=self.card.get())
        if sale:
            self.card.set("")       # never keep the full card number on screen
            self.tendered.set("")
            self._update(sale)
            if sale.change_cents:
                set_status(self, f"Give the customer {money(sale.change_cents)} change.")

    def remove_payment(self):
        iid = self.payments.selected()
        if self._need_sale() and iid:
            self._update(run(self, pos.remove_payment, self.app.conn, self.app.user, self.sale.purchase_id, int(iid)))

    def sign(self):
        if self._need_sale():
            self._update(run(self, pos.record_signature, self.app.conn, self.app.user, self.sale.purchase_id,
                             self.signer.get(), success="Signature recorded."))

    def complete(self):
        if not self._need_sale():
            return
        receipt = run(self, pos.complete, self.app.conn, self.app.user, self.sale.purchase_id,
                      success=f"Sale #{self.sale.purchase_id} completed.")
        if receipt:
            self._update(pos.get(self.app.conn, self.sale.purchase_id))
            ReceiptDialog(self, receipt, print_now=True)
            self.app.data_changed(skip=self)

    def void(self):
        if self._need_sale() and messagebox.askyesno("Void sale", f"Cancel sale #{self.sale.purchase_id}?", parent=self):
            self._update(run(self, pos.void, self.app.conn, self.app.user, self.sale.purchase_id,
                             success="Sale voided."))


class ReceiptDialog(tk.Toplevel):
    """Shows the receipt with Print and Save buttons."""

    def __init__(self, parent, receipt: receipts.Receipt, print_now: bool = False):
        super().__init__(parent)
        self.receipt = receipt
        self.title(f"Receipt {receipt.receipt_no}")
        self.transient(parent.winfo_toplevel())
        text = tk.Text(self, width=receipts.WIDTH + 2, height=30, font="TkFixedFont")
        text.insert("1.0", receipt.body)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=8, pady=8)
        self.msg = ttk.Label(self, foreground="#666", wraplength=380)
        self.msg.pack(anchor="w", padx=8)
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=8)
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Save as...", command=self.save_as).pack(side="right", padx=6)
        ttk.Button(bar, text="Print", command=self.print_).pack(side="right")
        if print_now:
            self.print_()

    def print_(self):
        path, sent = receipts.print_receipt(self.receipt)
        self.msg.configure(text=f"Sent to the printer. Copy saved to {path}" if sent
                           else f"No printer found. Saved to {path} - print it from there.")

    def save_as(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".txt",
                                            initialfile=f"{self.receipt.receipt_no}.txt",
                                            filetypes=[("Text files", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.receipt.body)
            self.msg.configure(text=f"Saved to {path}")
