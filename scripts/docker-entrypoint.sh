#!/bin/sh
# Container start-up: wait for the database, apply migrations, optionally seed demo data, then start the app.
set -e

python scripts/wait_for_db.py

flask init-db

if [ "${SEED_DEMO:-0}" = "1" ]; then
  # seed-demo refuses to run when users already exist, so restarts never duplicate data
  flask seed-demo || echo "Demo data not seeded (database already has users)."
fi

exec "$@"
