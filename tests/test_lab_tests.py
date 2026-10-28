"""SFWE12-7 (SRS 6.3.1, 6.3.2 and the Oct 1st field list)."""

import unittest

from clms import lab_tests as tr, patients
from clms.errors import InvalidState, PermissionDenied, ValidationError

from .helpers import CASHIER, COLLECTOR, DOCTOR, MANAGER, PATIENT_USER, PROVIDER_USER, TECH, DBTestCase


class TestRequestTests(DBTestCase):
    def accept(self, user=CASHIER, source="WALK_IN", patient=None, **kw):
        patient = patient or self.new_patient()
        return tr.accept_test(self.conn, user, source=source, patient_id=patient.patient_id,
                              physician=kw.pop("physician", DOCTOR), test_code=kw.pop("test_code", "CBC"), **kw)

    def test_all_personnel_accept_walk_in_and_phone(self):
        for user in (MANAGER, COLLECTOR, TECH, CASHIER):
            for source in ("WALK_IN", "PHONE"):
                with self.subTest(user=user.role, source=source):
                    req = self.accept(user, source)
                    self.assertEqual(req.source, source)
                    self.assertEqual(req.result_status, "pending")

    def test_external_users_cannot_enter(self):
        for user in (PATIENT_USER, PROVIDER_USER):
            with self.assertRaises(PermissionDenied):
                self.accept(user)

    def test_every_required_field_is_captured(self):
        p = self.new_patient()
        req = self.accept(patient=p, test_code="B123")
        # Report information
        self.assertRegex(req.report_id, r"^RPT-\d{8}-0001$")
        self.assertTrue(req.report_datetime)
        # Patient information
        self.assertEqual((req.patient_id, req.patient_name, req.patient_dob, req.patient_gender),
                         (p.patient_id, "Jane Doe", "1990-04-15", "Female"))
        self.assertEqual(req.patient_age, p.age)
        # Ordering physician
        self.assertEqual((req.physician_id, req.physician_name), ("AZ-12345", "Dr. Alice Grey"))
        # Test details defaulted from the catalog
        self.assertEqual((req.test_name, req.sample_type, req.result_units, req.reference_range),
                         ("T3 Uptake", "blood", "%", "24 - 39"))
        # Insurance copied from the patient
        self.assertEqual((req.insurance_provider, req.insurance_policy_number), ("Blue Cross", "BC-778899"))

    def test_report_ids_are_sequential(self):
        ids = [self.accept().report_id for _ in range(3)]
        self.assertEqual([i[-4:] for i in ids], ["0001", "0002", "0003"])

    def test_insurance_required_and_overridable(self):
        uninsured = self.new_patient(insurance_provider="", insurance_policy_number="")
        with self.assertRaisesRegex(ValidationError, "insurance"):
            self.accept(patient=uninsured)
        req = self.accept(patient=uninsured, insurance_provider="Medicare", insurance_policy_number="1EG4-TE5")
        self.assertEqual(req.insurance_provider, "Medicare")

    def test_physician_needs_id_name_and_contact(self):
        for doc in (tr.Physician("", "Dr. A", phone="5205550101"),
                    tr.Physician("ID1", "", phone="5205550101"),
                    tr.Physician("ID1", "Dr. A")):
            with self.subTest(doc=doc):
                with self.assertRaises(ValidationError):
                    self.accept(physician=doc)
        self.accept(physician=tr.Physician("id1", "Dr. A", email="a@clinic.org"))
        self.assertEqual(tr.get_physician(self.conn, "ID1").email, "a@clinic.org")

    def test_unknown_test_rejected(self):
        with self.assertRaises(Exception):
            self.accept(test_code="NOPE")

    def test_snapshot_survives_patient_deletion(self):
        p = self.new_patient()
        req = self.accept(patient=p)
        patients.delete(self.conn, MANAGER, p.patient_id)
        kept = tr.get(self.conn, req.report_id)
        self.assertIsNone(kept.patient_id)
        self.assertEqual(kept.patient_name, "Jane Doe")

    def test_full_lifecycle(self):
        req = self.accept()
        with self.assertRaises(InvalidState):  # results before collection
            tr.record_result(self.conn, TECH, req.report_id, result_value="5", performed_by="T1", machine_used="M1")
        with self.assertRaises(PermissionDenied):
            tr.record_collection(self.conn, CASHIER, req.report_id, sample_id="1234", collected_by="Sam")
        tr.record_collection(self.conn, COLLECTOR, req.report_id, sample_id="1234", collected_by="Sam Rivera",
                             collection_datetime="202208221340")
        with self.assertRaises(PermissionDenied):
            tr.record_result(self.conn, CASHIER, req.report_id, result_value="5", performed_by="T1", machine_used="M1")
        done = tr.record_result(self.conn, TECH, req.report_id, result_value="28", performed_by="TECH-07",
                                machine_used="Sysmex XN-1000", results_received_datetime="2022-08-22 15:00")
        self.assertEqual(done.result_status, "completed")
        self.assertEqual(done.collection_datetime, "2022-08-22 13:40")
        with self.assertRaises(PermissionDenied):
            tr.validate_result(self.conn, TECH, req.report_id)
        final = tr.validate_result(self.conn, MANAGER, req.report_id)
        self.assertEqual(final.result_status, "validated")
        with self.assertRaises(InvalidState):
            tr.record_result(self.conn, TECH, req.report_id, result_value="1", performed_by="x", machine_used="y")

    def test_sample_id_must_be_unique(self):
        a, b = self.accept(), self.accept()
        tr.record_collection(self.conn, COLLECTOR, a.report_id, sample_id="S1", collected_by="Sam")
        with self.assertRaises(ValidationError):
            tr.record_collection(self.conn, COLLECTOR, b.report_id, sample_id="S1", collected_by="Sam")

    def test_list_and_filter(self):
        p = self.new_patient()
        self.accept(patient=p)
        self.accept()
        self.assertEqual(len(tr.list_requests(self.conn)), 2)
        self.assertEqual(len(tr.list_requests(self.conn, patient_id=p.patient_id)), 1)
        self.assertEqual(len(tr.list_requests(self.conn, status="completed")), 0)


if __name__ == "__main__":
    unittest.main()
