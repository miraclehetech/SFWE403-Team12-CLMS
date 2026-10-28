"""Clinical Laboratory Management System (CLMS) - SFWE 403, Team 12.

Package layout
--------------
- ``database``      SQLite connection + schema (shared by every module)
- ``roles``         user types and the signed-in user (SRS 6.1.3)
- ``lab_info``      laboratory information storage (SRS 6.1.1)            SFWE12-2
- ``patients``      patient accounts and deletion rules (SRS 6.1.4-6.1.5)  SFWE12-4
- ``lab_tests``     test intake with every required field (SRS 6.3.1-6.3.2) SFWE12-7
- ``purchases``     test purchases and POS checkout (SRS 6.6.1-6.6.4)     SFWE12-19/20
- ``receipts``      receipt text, saving and printing (SRS 6.6.3)          SFWE12-20
- ``gui``           Tkinter user interface (SRS 6.1.2)                     SFWE12-2
"""

__version__ = "0.1.0"
