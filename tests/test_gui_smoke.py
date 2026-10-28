"""Drives the Tkinter GUI end to end. Skipped when Tk or a display is unavailable."""

import os
import unittest
from unittest import mock

try:
    import tkinter as tk
    from tkinter import messagebox
except ImportError:  # pragma: no cover
    tk = None

from clms import database, lab_info, lab_tests as test_requests, patients, purchases

from .helpers import CASHIER, COLLECTOR, MANAGER, TECH


def _display_ok() -> bool:
    if tk is None:
        return False
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(_display_ok(), "Tk display not available")
class GuiSmokeTest(unittest.TestCase):
    def setUp(self):
        from clms.gui.app import App
        self.errors = []
        patches = [
            mock.patch.object(messagebox, "showerror", side_effect=lambda t, m, **k: self.errors.append(m)),
            mock.patch.object(messagebox, "showinfo", side_effect=lambda t, m, **k: self.errors.append(m)),
            mock.patch.object(messagebox, "askyesno", return_value=True),
            mock.patch("clms.receipts.DEFAULT_RECEIPT_DIR", os.path.join(os.getcwd(), ".test-receipts")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.conn = database.connect(":memory:")
        self.app = App(self.conn, user=MANAGER)
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        self.conn.close()

    def test_full_counter_workflow(self):
        from clms.gui.lab_info_tab import LabInfoTab
        from clms.gui.patients_tab import PatientsTab
        from clms.gui.pos_tab import POSTab
        from clms.gui.lab_tests_tab import TestRequestsTab

        # Lab info: manager saves, title updates; others are read-only.
        lab = self.app.tab(LabInfoTab)
        lab.form.set(dict(name="Wildcat Lab", website="lab.example.edu", address="1 Main St", owner="UA",
                          phone="520-555-0100", working_hours="Mon-Fri 7-18"))
        lab.save()
        self.assertEqual(lab_info.get(self.conn).name, "Wildcat Lab")
        self.assertIn("Wildcat Lab", self.app.title())
        self.app.set_user(CASHIER)
        self.assertTrue(lab.save_btn.instate(["disabled"]))

        # Patients: cashier creates one; delete button disabled for cashier, enabled for collector.
        pt = self.app.tab(PatientsTab)
        pt.form.set(dict(first_name="Jane", last_name="Doe", date_of_birth="1990-04-15", gender="Female",
                         address="1 University Blvd", phone="520-555-0199", email="jane@example.com",
                         insurance_provider="Blue Cross", insurance_policy_number="BC-1"))
        pt.save()
        self.assertEqual(self.errors, [])
        jane = patients.search(self.conn, "Jane")[0]
        self.assertTrue(pt.delete_btn.instate(["disabled"]))
        self.app.set_user(COLLECTOR)
        self.assertFalse(pt.delete_btn.instate(["disabled"]))

        # Test request (phoned in) with insurance auto-filled from the patient.
        trt = self.app.tab(TestRequestsTab)
        trt.source.set("PHONE")
        trt.select_patient(jane.patient_id)
        self.assertEqual(trt.billing.vars["insurance_policy_number"].get(), "BC-1")
        trt.test_var.set(next(k for k in trt._tests if k.startswith("CBC")))
        trt.doctor.set(dict(physician_id="AZ-1", name="Dr. Grey", phone="520-555-0101"))
        trt.submit()
        self.assertEqual(self.errors, [])
        req = test_requests.list_requests(self.conn)[0]
        self.assertEqual((req.source, req.test_code), ("PHONE", "CBC"))
        trt.show_details(req.report_id)
        self.assertIn("HEALTH INSURANCE / BILLING", trt.details.get("1.0", "end"))

        # POS: bill the request, add a manual test, split payment, sign, complete.
        self.app.set_user(CASHIER)
        p = self.app.tab(POSTab)
        p.patient_var.set(next(k for k in p._patients if k.startswith(f"#{jane.patient_id}")))
        p.start()
        p.add_requests()
        p.test_var.set(next(k for k in p._tests if k.startswith("Urinalysis")))
        p.add_item()                                   # 35 + 25 = 60
        self.assertEqual(p.sale.total_cents, 6000)
        p.method.set("Credit card"); p.amount.set("40"); p.card.set("4111111111111111")
        p.add_payment()
        p.method.set("Cash"); p._method_changed(); p.amount.set("20"); p.tendered.set("50")
        p.add_payment()
        self.assertEqual((p.sale.balance_cents, p.sale.change_cents), (0, 3000))
        p.complete()                                   # blocked: no signature
        self.assertTrue(any("signature" in e for e in self.errors))
        self.errors.clear()
        p.sign()
        p.complete()
        self.assertEqual(self.errors, [])
        self.assertEqual(purchases.get(self.conn, p.sale.purchase_id).status, "COMPLETED")
        self.app.update()


if __name__ == "__main__":
    unittest.main()
