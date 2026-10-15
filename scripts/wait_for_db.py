"""Block until the configured database accepts connections (used by Docker start-up).

Usage: python scripts/wait_for_db.py [timeout_seconds]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text  # noqa: E402

from config import build_database_uri  # noqa: E402


def main():
    timeout = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    uri = build_database_uri()
    engine = create_engine(uri, pool_pre_ping=True)
    deadline = time.time() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print(f"Database is ready (attempt {attempt}).")
            return 0
        except Exception as exc:  # noqa: BLE001
            if time.time() > deadline:
                print(f"Database not reachable after {timeout}s: {exc}", file=sys.stderr)
                return 1
            print(f"Waiting for database... ({exc.__class__.__name__})")
            time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())
