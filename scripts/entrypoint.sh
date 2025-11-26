#!/usr/bin/env bash
set -euo pipefail

ENV_NAME=${ENV_NAME:-biomni_e1}
DATA_DIR="${BIOMNI_DATA_DIR:-/workspace/data}"
APP_MODULE=${BIOMNI_APP_MODULE:-}
TMPDIR=${TMPDIR:-/workspace/.tmp}

mkdir -p "$TMPDIR"

readarray -t APP_CANDIDATES <<'CAND'
biomni_esqlabs_app.main:app
biomni.web.app:app
main:app
app.main.app
CAND
if [[ -n "$APP_MODULE" ]]; then
  APP_CANDIDATES=("$APP_MODULE" "${APP_CANDIDATES[@]}")
fi

# Ensure mount exists and is writable
mkdir -p "$DATA_DIR"
if ! touch "$DATA_DIR/.rwtest" 2>/dev/null; then
  echo "ERROR: $DATA_DIR is not writable. Bind-mount ./data/biomni_data." >&2
  exit 1
fi
rm -f "$DATA_DIR/.rwtest"

# Optional: small preflight checks (no large downloads)
# micromamba run -n "$ENV_NAME" python -m biomni.tools.preflight --data "$DATA_DIR" || true

# Start web UI if available, else fall back to agent runner
for candidate in "${APP_CANDIDATES[@]}"; do
  module="${candidate%%:*}"
  attr="${candidate#*:}"
  if [[ "$module" == "$attr" ]]; then
    attr=""
  fi
  if micromamba run -n "$ENV_NAME" python - <<PY
import importlib
import sys
module = ${module@Q}
attr = ${attr@Q}
try:
    mod = importlib.import_module(module)
except ModuleNotFoundError as exc:
    print(f"Skipping {candidate}: {exc}", file=sys.stderr)
    sys.exit(1)
except Exception as exc:
    print(f"Error importing {candidate}: {exc}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
if attr and not hasattr(mod, attr):
    sys.exit(1)
sys.exit(0)
PY
  then
    exec micromamba run -n "$ENV_NAME" uvicorn "$candidate" --host 0.0.0.0 --port "${PORT:-8001}"
  fi
done

echo "[entrypoint] No ASGI app module found; falling back to biomni agent" >&2
if ! micromamba run -n "$ENV_NAME" python - <<'PY'
import time
try:
    from biomni.agent import A1
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"Unable to start Biomni agent: {exc}")

agent = A1()
print("Biomni agent initialized. Awaiting tasks...")
while True:
    time.sleep(3600)
PY
then
  echo "[entrypoint] Biomni agent failed to initialize" >&2
  exit 1
fi
