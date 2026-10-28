"""SFWE12-2 (SRS 6.1.1) and SFWE12-4 (SRS 6.1.4, 6.1.5)."""

import unittest

from clms import lab_info, patients, purchases
from clms.errors import NotFound, PermissionDenied, ValidationError

from .helpers import CASHIER, COLLECTOR, MANAGER, PATIENT_USER, TECH, DBTestCase, make_patient

LAB = lab_info.LabInfo(
    name="Wildcat Clinical Lab",
    website="https://lab.example.edu",
    address="1230 N Cherry Ave, Tucson, AZ 85721",
    owner="University of Arizona",
    phone="520-555-0100",
    working_hours="Mon-Fri 7:00-18:00, Sat 8:00-12:00",
)


class LabInfoTests(DBTestCase):
    def test_manager_can_store_all_six_fields(self):
        lab_info.update(self.conn, MANAGER, LAB)
        self.assertEqual(lab_info.get(self.conn), LAB)

    def test_only_manager_can_change(self):
        for user in (COLLECTOR, TECH, CASHIER, PATIENT_USER):
            with self.subTest(user=user.role):
                with self.assertRaises(PermissionDenied):
                    lab_info.update(self.conn, user, LAB)

    def test_rejects_missing_or_bad_fields(self):
        bad = lab_info.LabInfo(**{**LAB.__dict__, "working_hours": " "})
        with self.assertRaisesRegex(ValidationError, "Working hours"):
            lab_info.update(self.conn, MANAGER, bad)
        bad = lab_info.LabInfo(**{**LAB.__dict__, "phone": "12"})
        with self.assertRaises(ValidationError):
            lab_info.update(self.conn, MANAGER, bad)
        bad = lab_info.LabInfo(**{**LAB.__dict__, "website": "not a url"})
        with self.assertRaises(ValidationError):
            lab_info.update(self.conn, MANAGER, bad)


class PatientTests(DBTestCase):
    def test_all_lab_personnel_can_create_and_update(self):
        for user in (MANAGER, COLLECTOR, TECH, CASHIER):
            with self.subTest(user=user.role):
                p = patients.create(self.conn, user, make_patient(last_name=user.username))
                p.phone = "520-555-7777"
                p.insurance_provider, p.insurance_policy_number = "Aetna", "AET-1"
                updated = patients.update(self.conn, user, p)
                self.assertEqual(updated.phone, "520-555-7777")
                self.assertEqual(updated.insurance_provider, "Aetna")

    def test_stores_required_information(self):
        p = self.new_patient()
        stored = patients.get(self.conn, p.patient_id)
        for attr in ("first_name", "last_name", "date_of_birth", "address", "phone", "email",
                     "insurance_provider", "insurance_policy_number", "insurance_coverage"):
            self.assertEqual(getattr(stored, attr), getattr(make_patient(), attr), attr)

    def test_non_staff_cannot_create(self):
        with self.assertRaises(PermissionDenied):
            patients.create(self.conn, PATIENT_USER, make_patient())

    def test_validation(self):
        cases = {
            "missing name": dict(first_name=""),
            "future dob": dict(date_of_birth="2999-01-01"),
            "bad dob": dict(date_of_birth="04/15/1990"),
            "bad phone": dict(phone="555"),
            "bad email": dict(email="jane@"),
            "half insurance": dict(insurance_policy_number=""),
            "bad gender": dict(gender="?"),
        }
        for name, override in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValidationError):
                    patients.create(self.conn, CASHIER, make_patient(**override))

    def test_only_collector_or_manager_can_delete(self):
        for user in (TECH, CASHIER, PATIENT_USER):
            p = self.new_patient()
            with self.subTest(user=user.role):
                with self.assertRaises(PermissionDenied):
                    patients.delete(self.conn, user, p.patient_id)
        for user in (COLLECTOR, MANAGER):
            p = self.new_patient()
            with self.subTest(user=user.role):
                patients.delete(self.conn, user, p.patient_id)
                with self.assertRaises(NotFound):
                    patients.get(self.conn, p.patient_id)

    def test_cannot_delete_with_open_sale(self):
        p = self.new_patient()
        sale = purchases.start(self.conn, CASHIER, patient_id=p.patient_id)
        with self.assertRaises(ValidationError):
            patients.delete(self.conn, MANAGER, p.patient_id)
        purchases.void(self.conn, CASHIER, sale.purchase_id)
        patients.delete(self.conn, MANAGER, p.patient_id)

    def test_search(self):
        a = self.new_patient(first_name="Ana", last_name="Lopez", phone="520-111-2222")
        self.new_patient(first_name="Ben", last_name="Smith", insurance_policy_number="XYZ-9")
        self.assertEqual([p.patient_id for p in patients.search(self.conn, "lopez")], [a.patient_id])
        self.assertEqual(len(patients.search(self.conn, "XYZ")), 1)
        self.assertEqual(len(patients.search(self.conn, str(a.patient_id))), 1)
        self.assertEqual(len(patients.search(self.conn)), 2)


if __name__ == "__main__":
    unittest.main()
