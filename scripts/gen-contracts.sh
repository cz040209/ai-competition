#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/packages/contracts/src/schema.d.ts"

cd "$ROOT/apps/api"
.venv/bin/python -c '
import json

from kira.api.app import create_app

print(json.dumps(create_app().openapi()))
' > openapi.json

cd "$ROOT"
npx --yes openapi-typescript@7 "$ROOT/apps/api/openapi.json" -o "$OUT"
echo "wrote $OUT"
