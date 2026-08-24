#!/usr/bin/env bash
set -euo pipefail

echo "Applying migrations…"
attempt=1
until alembic upgrade head; do
  if [ "$attempt" -ge 10 ]; then
    echo "Database did not become reachable after ${attempt} attempts." >&2
    exit 1
  fi
  echo "Database is not reachable yet; retrying…" >&2
  attempt=$((attempt + 1))
  sleep 1
done

if [ "${SEED_DEMO:-1}" = "1" ]; then
  echo "Seeding the demo user…"
  python -m kira.seed
fi

exec uvicorn kira.api.app:app --host 0.0.0.0 --port 8000
