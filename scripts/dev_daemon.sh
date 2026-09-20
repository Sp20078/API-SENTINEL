#!/usr/bin/env bash
# Start demo services detached (setsid) so they survive the launching shell.
# Usage: scripts/dev_daemon.sh start|status|stop
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$ROOT/.run"; mkdir -p "$LOG"

port_up() { # try IPv4 then IPv6/localhost
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && return 0
  if command -v curl >/dev/null 2>&1; then
    curl -s -o /dev/null --max-time 1 "http://localhost:$1/" 2>/dev/null && return 0
  fi
  return 1
}

start_one() { # name dir cmd log
  local name="$1" dir="$2" cmd="$3" log="$LOG/$4"
  if port_up "$5"; then
    echo "$name: already up (port $5)"
    return 0
  fi
  (cd "$ROOT/$dir" && setsid bash -c "$cmd" >"$log" 2>&1 < /dev/null &)
  echo "$name: launching on port $5 (log .run/$4)"
}

case "${1:-start}" in
  start)
    start_one "demo-api" "vulnerable-demo-api" \
      "exec venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --log-level warning" \
      "demo-api.log" 8001
    start_one "scanner-engine" "sentinel-engine" \
      "exec venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning" \
      "scanner-engine.log" 8000
    start_one "weather-providers" "weather-providers" \
      "exec venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8002 --log-level warning" \
      "weather-providers.log" 8002
    start_one "frontend" "frontend" \
      "exec npm run dev" \
      "frontend.log" 5173
    ;;
  status)
    for p in 8001 8000 8002 5173; do
      if port_up "$p"; then echo "$p UP"; else echo "$p DOWN"; fi
    done
    ;;
  stop)
    pkill -f "uvicorn app.main:app" 2>/dev/null
    pkill -f "vite" 2>/dev/null
    echo "stopped uvicorn/vite processes"
    ;;
  *) echo "usage: $0 start|status|stop" >&2; exit 2 ;;
esac
