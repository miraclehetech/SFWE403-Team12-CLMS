"""Start the Clinical Laboratory Management System GUI.

    python main.py                 # uses ~/.clms/clms.db
    python main.py --db demo.db    # use another database file
"""

import argparse

from clms.gui.app import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clinical Laboratory Management System")
    parser.add_argument("--db", help="SQLite database file (default: ~/.clms/clms.db)")
    main(parser.parse_args().db)
