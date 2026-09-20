#!/usr/bin/env bash
# ============================================================================
# API Sentinel — one-command demo launcher
#
# Starts every service that exists, in dependency order, for the live demo:
#   1. vulnerable-demo-api  → http://127.0.0.1:8001  (the scan target)
#   2. sentinel-engine      → http://127.0.0.1:8000  (scanner + Trust Router)
#   3. weather-providers    → http://127.0.0.1:8002  (Trust Router simulators)
#   4. frontend             → http://localhost:5173  (dashboard; once built)
#
# Usage:
#   ./run_all.sh              # start everything available, block until Ctrl+C
#   ./run_all.sh --keep-mode  # do NOT reset the demo API to vulnerable mode
#   ./run_all.sh --help
#
# Behavior:
#   - Services already listening on their port are left alone ("already running").
#   - Missing venvs/node_modules are created and dependencies installed quietly.
#   - The demo API is reset to VULNERABLE mode on startup (demo's known-good
#     starting state) unless --keep-mode is passed.
#   - Logs are written to .run/*.log; Ctrl+C (or TERM) stops everything started.
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT/.run"
mkdir -p "$LOG_DIR"

DEMO_DIR="$ROOT/vulnerable-demo-api"
ENGINE_DIR="$ROOT/sentinel-engine"
WEATHER_DIR="$ROOT/weather-providers"
FRONTEND_DIR="$ROOT/frontend"

DEMO_PORT=8001
ENGINE_PORT=8000
WEATHER_PORT=8002
FRONTEND_PORT=5173

KEEP_MODE=0
for arg in "$@"; do
  case "$arg" in
    --keep-mode) KEEP_MODE=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

PIDS=()
CLEANED=0
cleanup() {
  [ "$CLEANED" -eq 1 ] && return 0
  CLEANED=1
  echo ""
  echo "[run_all] Shutting down..."
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  echo "[run_all] Stopped. Logs in $LOG_DIR/"
}
trap cleanup EXIT INT TERM

# --- helpers ---------------------------------------------------------------
port_in_use() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

if command -v curl >/dev/null 2>&1; then
  http_ok() { curl -fs -o /dev/null --max-time 2 "$1"; }
else
  http_ok() { python3 -c "import sys,urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2)" "$1" >/dev/null 2>&1; }
fi

wait_for_url() { # url name log
  local url="$1" name="$2" log="$3" i
  for i in $(seq 1 60); do
    if http_ok "$url"; then return 0; fi
    if ! kill -0 "${PIDS[-1]}" 2>/dev/null; then
      echo "[run_all] ERROR: $name exited during startup — see $log" >&2
      tail -n 20 "$log" >&2 || true
      exit 1
    fi
    sleep 0.5
  done
  echo "[run_all] ERROR: $name not healthy at $url after 30s — see $log" >&2
  exit 1
}

start_python_service() { # dir port name entrypoint [marker_path]
  local dir="$1"
  local port="$2"
  local name="$3"
  local entry="$4"
  local marker="${5:-}"
  local log="$LOG_DIR/$name.log"
  if [ ! -f "$dir/$entry" ]; then
    echo "[run_all] SKIP  $name (not built yet — will auto-start once implemented)"
    return 0
  fi
  if port_in_use "$port"; then
    echo "[run_all] SKIP  $name — port $port already in use (assuming it is running)"
    # Stale-code guard: if the running service predates a known route, it is
    # an OLD process (e.g. started before a feature landed) — say so loudly.
    if [ -n "$marker" ]; then
      if command -v curl >/dev/null 2>&1; then
        if ! curl -fs -o /dev/null --max-time 2 "http://127.0.0.1:$port$marker"; then
          echo "[run_all] WARN  $name on :$port looks STALE (missing $marker) — restart it!"
          echo "[run_all]       e.g.: kill $(ss -tlnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | head -1) && ./run_all.sh"
        fi
      fi
    fi
    return 0
  fi
  if [ ! -x "$dir/venv/bin/python" ]; then
    echo "[run_all] SETUP creating venv for $name..."
    python3 -m venv "$dir/venv"
    "$dir/venv/bin/pip" install -q -r "$dir/requirements-dev.txt"
  fi
  echo "[run_all] START $name on http://127.0.0.1:$port  (log: .run/$name.log)"
  (cd "$dir" && venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$port") >"$log" 2>&1 &
  PIDS+=($!)
  wait_for_url "http://127.0.0.1:$port/health" "$name" "$log"
}

start_frontend() {
  local log="$LOG_DIR/frontend.log"
  if [ ! -f "$FRONTEND_DIR/package.json" ]; then
    echo "[run_all] SKIP  frontend (not built yet — will auto-start once implemented)"
    return 0
  fi
  if port_in_use "$FRONTEND_PORT"; then
    echo "[run_all] SKIP  frontend — port $FRONTEND_PORT already in use"
    return 0
  fi
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "[run_all] SETUP npm install for frontend..."
    (cd "$FRONTEND_DIR" && npm install --silent) >>"$log" 2>&1
  fi
  echo "[run_all] START frontend on http://localhost:$FRONTEND_PORT  (log: .run/frontend.log)"
  (cd "$FRONTEND_DIR" && npm run dev -- --port "$FRONTEND_PORT" --strictPort) >>"$log" 2>&1 &
  PIDS+=($!)
}

# --- launch ----------------------------------------------------------------
start_python_service "$DEMO_DIR" "$DEMO_PORT" "demo-api" "app/main.py" "/api/products"
start_python_service "$ENGINE_DIR" "$ENGINE_PORT" "scanner-engine" "app/main.py" "/trust-router/providers"
start_python_service "$WEATHER_DIR" "$WEATHER_PORT" "weather-providers" "app/main.py" "/data-mode"
start_frontend

if port_in_use "$DEMO_PORT" && [ "$KEEP_MODE" -ne 0 ]; then
  : # --keep-mode: leave the demo API's current mode untouched
elif port_in_use "$DEMO_PORT"; then
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -o /dev/null --max-time 2 -X POST "http://127.0.0.1:$DEMO_PORT/admin/mode" \
      -H 'Content-Type: application/json' -d '{"mode":"vulnerable"}' || true
  else
    python3 -c "import json,urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:$DEMO_PORT/admin/mode', data=json.dumps({'mode':'vulnerable'}).encode(), headers={'Content-Type':'application/json'}), timeout=2)" || true
  fi
  echo "[run_all] Demo API mode reset to 'vulnerable' (demo starting state)"
fi

echo ""
echo "================================ API Sentinel — demo is up ================"
echo "  Dashboard        : http://localhost:$FRONTEND_PORT"
echo "  Scanner engine   : http://127.0.0.1:$ENGINE_PORT/health"
echo "  Demo target API  : http://127.0.0.1:$DEMO_PORT/health"
echo "  Weather providers: http://127.0.0.1:$WEATHER_PORT/health   (Trust Router demo)"
echo ""
echo "  Hero demo check (vulnerable mode):"
echo "    curl -s -H 'Authorization: Bearer alice-token' \\"
echo "         http://127.0.0.1:$DEMO_PORT/api/orders/order-1002   # expect 200 (the bug)"
echo ""
echo "  Press Ctrl+C to stop everything."
echo "==========================================================================="
echo ""

wait
