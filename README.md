# Clinical Laboratory Management System (CLMS)

SFWE 403 · Fall 2026 · Team 12

A desktop application (Python + Tkinter + SQLite) for running a clinical laboratory's front
desk: patient accounts, test intake, and point-of-sale checkout.

This repository currently contains the **Core GUI & Patients** epic (SFWE12-21), implemented
by ZhengXiao He.

| Jira | Story | SRS | Where |
|------|-------|-----|-------|
| SFWE12-2  | Laboratory information storage and a usable CLMS GUI | 6.1.1, 6.1.2 | `clms/lab_info.py`, `clms/gui/` |
| SFWE12-4  | Staff create/update patients; only collectors and the manager delete | 6.1.4, 6.1.5 | `clms/patients.py`, `clms/gui/patients_tab.py` |
| SFWE12-7  | Accept walk-in and phoned-in test requests with every required field | 6.3.1, 6.3.2, Oct 1 note | `clms/lab_tests.py`, `clms/gui/lab_tests_tab.py` |
| SFWE12-19 | Process laboratory test purchases through the GUI | 6.6.1 | `clms/purchases.py`, `clms/gui/pos_tab.py` |
| SFWE12-20 | POS checkout: signature, receipt, cash/debit/credit | 6.6.2–6.6.4 | `clms/purchases.py`, `clms/receipts.py`, `clms/gui/pos_tab.py` |

## Running it

Requires Python 3.10+ with Tkinter (bundled with the python.org installers on Windows and macOS;
on Ubuntu/Debian run `sudo apt install python3-tk`). There are no other dependencies.

```bash
python main.py               # data is kept in ~/.clms/clms.db
python main.py --db demo.db  # or use a separate database file
```

Use the **Signed in as** drop-down at the top right to switch between the four staff roles.
It stands in for the login screen until SFWE12-5/SFWE12-6 are merged.

## Running the tests

```bash
python -m unittest -v
```

The service-layer tests use an in-memory database. `tests/test_gui_smoke.py` drives the
whole counter workflow through the real Tkinter widgets and is skipped automatically when no
display is available.

## What each requirement does

**6.1.1 Laboratory information** – name, website, address, owner, phone and working hours are
stored in one record. Everyone can see them; only the laboratory manager can edit them. The
lab name appears in the window title and the receipt header.

**6.1.4 / 6.1.5 Patients** – all laboratory personnel can create and update a patient's name,
date of birth, gender, address, phone, email and insurance (provider, policy number, coverage).
Deleting is limited to the specimen collector and laboratory manager, and is blocked while the
patient has an unfinished sale. Test reports keep their own copy of the patient's details, so
removing an account does not change past reports.

**6.3.1 / 6.3.2 Test requests** – a request is marked *walk-in* (patient brought the order) or
*phoned in* (doctor's office called). Every request carries the fields listed in the Oct 1st
note, grouped as:

- Report information: report ID (`RPT-YYYYMMDD-####`), report date & time
- Patient information: patient ID, name, date of birth / age, gender
- Ordering physician: physician ID/license, name (contact phone or email also required)
- Test execution: sample type, sample ID, collection date & time, collected by, performed by,
  machine/instrument used
- Test results: test name, result value, units, reference range, status
  (`pending` → `completed` → `validated`), results received date & time
- Health insurance / billing: insurance provider, policy number

Insurance is pre-filled from the patient's account and can be changed at intake. Collection is
recorded by a specimen collector or the manager, results by a technician or the manager, and
validation by the manager.

**6.6.1 Purchases** – staff open a sale for a patient (or a named walk-in customer), add tests
from the catalog manually, or pull in the patient's accepted test requests with one click. A
test request can only be on one active sale.

**6.6.2 Signature** – the customer signs the paper form; staff record who signed. A sale cannot
be completed without it, and the receipt includes a signature line.

**6.6.3 Receipts** – completing a sale creates a receipt for the whole purchase, stores it in the
database, saves it to `~/.clms/receipts/<receipt no>.txt`, and sends it to the default printer
(`os.startfile` on Windows, `lp`/`lpr` on macOS/Linux).

**6.6.4 Payment types** – cash, debit and credit, and any combination of them on one sale.
Cash may exceed the balance (change is calculated). Card numbers are checked with the Luhn
algorithm and only the last four digits are stored. No real card processor is defined in the
SRS, so card payments get a simulated authorization reference.

## Project layout

```
main.py                 entry point
clms/
  database.py           SQLite schema, seed catalog, connection helper
  roles.py              user types (6.1.3) and permission checks
  events.py             hook for the transaction log (SFWE12-16)
  validators.py         shared input checks and money helpers
  lab_info.py           SFWE12-2
  patients.py           SFWE12-4
  lab_tests.py          SFWE12-7 (catalog, physicians, test requests)
  purchases.py          SFWE12-19 / SFWE12-20
  receipts.py           SFWE12-20
  gui/                  Tkinter screens (one module per tab)
tests/                  unittest suite
```

## Notes for teammates

- **Login (SFWE12-5/6):** produce a `clms.roles.User` and pass it to `App(conn, user=...)`, then
  remove the role drop-down in `gui/app.py`.
- **Transaction log (SFWE12-16):** every change calls `clms.events.emit(event, user, **details)`;
  call `events.subscribe(listener)` to write them to your log. Event names include
  `patient.created`, `test.accepted`, `purchase.payment` and `purchase.completed`.
- **Machine result import (SFWE12-10):** after parsing a `.txt` result line, call
  `lab_tests.record_result(...)` for the report whose `sample_id` matches the barcode.
- **Barcodes (SFWE12-9):** store the printed barcode with `lab_tests.record_collection(...)`.
- **Inventory (SFWE12-12):** subscribe to `test.completed` to deduct reagents.
- All money is stored in integer cents.
