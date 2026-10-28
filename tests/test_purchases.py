"""SFWE12-19 (SRS 6.6.1) and SFWE12-20 (SRS 6.6.2-6.6.4)."""

import unittest

from clms import events, lab_tests as tr, purchases as pos, receipts
from clms.errors import InvalidState, PermissionDenied, ValidationError

from .helpers import CASHIER, DOCTOR, MANAGER, PATIENT_USER, DBTestCase

VISA = "4111 1111 1111 1111"


class PurchaseTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.patient = self.new_patient()
        self.sale = pos.start(self.conn, CASHIER, patient_id=self.patient.patient_id)

    def test_manual_items_and_totals(self):
        pos.add_item(self.conn, CASHIER, self.sale.purchase_id, "CBC")          # 35.00
        sale = pos.add_item(self.conn, CASHIER, self.sale.purchase_id, "UA", 2)  # 2 x 25.00
        self.assertEqual(sale.total_cents, 8500)
        sale = pos.add_item(self.conn, CASHIER, self.sale.purchase_id, "UA")     # merges -> qty 3
        self.assertEqual([i.quantity for i in sale.items], [1, 3])
        sale = pos.remove_item(self.conn, CASHIER, sale.purchase_id, sale.items[0].item_id)
        self.assertEqual(sale.total_cents, 7500)

    def test_bad_quantities_and_codes(self):
        for qty in (0, -1, 21, "x"):
            with self.subTest(qty=qty), self.assertRaises(ValidationError):
                pos.add_item(self.conn, CASHIER, self.sale.purchase_id, "CBC", qty)
        with self.assertRaises(Exception):
            pos.add_item(self.conn, CASHIER, self.sale.purchase_id, "NOPE")

    def test_non_staff_cannot_sell(self):
        with self.assertRaises(PermissionDenied):
            pos.start(self.conn, PATIENT_USER, customer_name="Someone")

    def test_bill_accepted_test_request_once(self):
        req = tr.accept_test(self.conn, CASHIER, source="WALK_IN", patient_id=self.patient.patient_id,
                             physician=DOCTOR, test_code="LIPID")
        self.assertEqual(len(tr.unbilled_requests(self.conn, self.patient.patient_id)), 1)
        sale = pos.add_test_request(self.conn, CASHIER, self.sale.purchase_id, req.report_id)
        self.assertEqual(sale.items[0].report_id, req.report_id)
        self.assertEqual(sale.total_cents, 4800)
        self.assertEqual(tr.unbilled_requests(self.conn, self.patient.patient_id), [])
        other = pos.start(self.conn, CASHIER, patient_id=self.patient.patient_id)
        with self.assertRaises(ValidationError):
            pos.add_test_request(self.conn, CASHIER, other.purchase_id, req.report_id)
        pos.void(self.conn, CASHIER, self.sale.purchase_id)   # voiding frees it again
        pos.add_test_request(self.conn, CASHIER, other.purchase_id, req.report_id)

    def test_split_payment_with_change_signature_and_receipt(self):
        pos.add_item(self.conn, CASHIER, self.sale.purchase_id, "CBC")    # 35.00
        pos.add_item(self.conn, CASHIER, self.sale.purchase_id, "A1C")    # 39.00 -> 74.00
        pos.add_payment(self.conn, CASHIER, self.sale.purchase_id, "credit", "50.00", card_number=VISA)
        pos.add_payment(self.conn, CASHIER, self.sale.purchase_id, "DEBIT", 10, card_number="5555555555554444")
        sale = pos.add_payment(self.conn, CASHIER, self.sale.purchase_id, "CASH", "14.00", tendered="20")
        self.assertEqual(sale.balance_cents, 0)
        self.assertEqual(sale.change_cents, 600)
        self.assertEqual(sale.payments[0].card_last4, "1111")

        with self.assertRaisesRegex(InvalidState, "signature"):
            pos.complete(self.conn, CASHIER, self.sale.purchase_id)
        pos.record_signature(self.conn, CASHIER, self.sale.purchase_id, "Jane Doe")
        receipt = pos.complete(self.conn, CASHIER, self.sale.purchase_id)

        self.assertEqual(pos.get(self.conn, self.sale.purchase_id).status, "COMPLETED")
        for text in ("Complete Blood Count", "$74.00", "Credit ****1111", "Debit ****4444",
                     "Cash", "$20.00", "CHANGE", "$6.00", "Jane Doe", "Signature:"):
            self.assertIn(text, receipt.body)
        self.assertNotIn("4111 1111", receipt.body)
        self.assertEqual(receipts.get(self.conn, self.sale.purchase_id).receipt_no, receipt.receipt_no)

        path, _sent = receipts.print_receipt(receipt, self.tmp.name)
        self.assertEqual(path.read_text(), receipt.body)

        with self.assertRaises(InvalidState):  # completed sales are frozen
            pos.add_item(self.conn, CASHIER, self.sale.purchase_id, "UA")

    def test_cash_overpayment_applies_only_balance(self):
        pos.add_item(self.conn, CASHIER, self.sale.purchase_id, "U123")   # 18.00
        sale = pos.add_payment(self.conn, CASHIER, self.sale.purchase_id, "CASH", 20)
        self.assertEqual((sale.paid_cents, sale.change_cents, sale.balance_cents), (1800, 200, 0))
        with self.assertRaises(InvalidState):
            pos.add_payment(self.conn, CASHIER, self.sale.purchase_id, "CASH", 1)

    def test_payment_rules(self):
        with self.assertRaisesRegex(InvalidState, "at least one test"):
            pos.add_payment(self.conn, CASHIER, self.sale.purchase_id, "CASH", 10)
        pos.add_item(self.conn, CASHIER, self.sale.purchase_id, "CBC")  # 35.00
        bad = [
            ("BITCOIN", 10, {}),
            ("CREDIT", 40, {"card_number": VISA}),                    # more than balance
            ("CREDIT", 10, {"card_number": "4111111111111112"}),      # fails Luhn
            ("DEBIT", 10, {}),                                        # no card
            ("CASH", "abc", {}),
            ("CASH", 0, {}),
            ("CASH", 30, {"tendered": 20}),                           # tendered < amount
        ]
        for method, amount, kw in bad:
            with self.subTest(method=method, amount=amount, kw=kw):
                with self.assertRaises(ValidationError):
                    pos.add_payment(self.conn, CASHIER, self.sale.purchase_id, method, amount, **kw)

    def test_complete_requires_full_payment_and_items(self):
        pos.record_signature(self.conn, CASHIER, self.sale.purchase_id, "Jane Doe")
        with self.assertRaisesRegex(InvalidState, "at least one test"):
            pos.complete(self.conn, CASHIER, self.sale.purchase_id)
        pos.add_item(self.conn, CASHIER, self.sale.purchase_id, "CBC")
        pos.add_payment(self.conn, CASHIER, self.sale.purchase_id, "CASH", 10)
        with self.assertRaisesRegex(InvalidState, r"\$25\.00"):
            pos.complete(self.conn, CASHIER, self.sale.purchase_id)

    def test_remove_payment_and_item_order(self):
        sale = pos.add_item(self.conn, CASHIER, self.sale.purchase_id, "CBC")
        sale = pos.add_payment(self.conn, CASHIER, sale.purchase_id, "CASH", 5)
        with self.assertRaises(InvalidState):
            pos.remove_item(self.conn, CASHIER, sale.purchase_id, sale.items[0].item_id)
        sale = pos.remove_payment(self.conn, CASHIER, sale.purchase_id, sale.payments[0].payment_id)
        pos.remove_item(self.conn, CASHIER, sale.purchase_id, sale.items[0].item_id)

    def test_walk_in_customer_without_account(self):
        sale = pos.start(self.conn, MANAGER, customer_name="Walk-in Customer")
        self.assertIsNone(sale.patient_id)
        with self.assertRaises(ValidationError):
            pos.start(self.conn, MANAGER)

    def test_events_are_emitted_for_transaction_log(self):
        seen = []
        listener = lambda name, user, details: seen.append(name)
        events.subscribe(listener)
        try:
            pos.add_item(self.conn, CASHIER, self.sale.purchase_id, "CBC")
            pos.add_payment(self.conn, CASHIER, self.sale.purchase_id, "CASH", 35)
            pos.record_signature(self.conn, CASHIER, self.sale.purchase_id, "Jane")
            pos.complete(self.conn, CASHIER, self.sale.purchase_id)
        finally:
            events.unsubscribe(listener)
        self.assertEqual(seen, ["purchase.item_added", "purchase.payment", "purchase.signed", "purchase.completed"])


if __name__ == "__main__":
    unittest.main()
