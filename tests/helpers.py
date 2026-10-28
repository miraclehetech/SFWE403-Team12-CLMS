"""Shared fixtures for the unit tests."""

import tempfile
import unittest

from clms import database, lab_tests as test_requests, patients
from clms.roles import Role, User

MANAGER = User("manager", "Morgan Lee", Role.LAB_MANAGER)
COLLECTOR = User("collector", "Sam Rivera", Role.SPECIMEN_COLLECTOR)
TECH = User("tech", "Taylor Chen", Role.LAB_TECHNICIAN)
CASHIER = User("cashier", "Casey Brooks", Role.CASHIER)
PATIENT_USER = User("pat", "Pat Doe", Role.PATIENT)
PROVIDER_USER = User("drx", "Dr. X", Role.HEALTHCARE_PROVIDER)

DOCTOR = test_requests.Physician("az-12345", "Dr. Alice Grey", phone="520-555-0101")


def make_patient(**overrides) -> patients.Patient:
    data = dict(
        first_name="Jane",
        last_name="Doe",
        date_of_birth="1990-04-15",
        gender="Female",
        address="1 University Blvd, Tucson, AZ",
        phone="(520) 555-0199",
        email="jane@example.com",
        insurance_provider="Blue Cross",
        insurance_policy_number="BC-778899",
        insurance_coverage="80% after deductible",
    )
    data.update(overrides)
    return patients.Patient(**data)


class DBTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = database.connect(":memory:")
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def new_patient(self, **overrides) -> patients.Patient:
        return patients.create(self.conn, CASHIER, make_patient(**overrides))
