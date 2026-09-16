#!/bin/bash
# Runs the suite. Starts both servers fresh, runs the tests, tears them down.
#
# The servers are started fresh every time on purpose. tests/serve.py reads the
# templates once at import, so a stale process serves the old page and the
# browser tests fail against code that is actually fine. allow_reuse_address
# means a second process binds silently rather than erroring, so a stale one is
# invisible unless you kill it by port.
#
#   tests/run.sh          # everything
#   tests/run.sh py       # Python only (no servers needed, ~20s)
#   tests/run.sh js       # browser only
#   tests/run.sh <path>   # one file, e.g. tests/run.sh tests/runs_test.js
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

PY=python3.12
WHAT="${1:-all}"

kill_port() {
  local pids
  pids=$(lsof -ti tcp:"$1" 2>/dev/null || true)
  [ -n "$pids" ] && kill -9 $pids 2>/dev/null
  return 0
}

start_servers() {
  kill_port 5199; kill_port 5203
  $PY tests/serve.py > /tmp/seoq-serve.log 2>&1 &
  SERVE_PID=$!
  PORT=5203 $PY app.py > /tmp/seoq-app.log 2>&1 &
  APP_PID=$!
  for _ in $(seq 1 40); do
    if curl -sf -o /dev/null http://127.0.0.1:5199/ \
       && curl -sf -o /dev/null http://127.0.0.1:5203/adtini; then
      return 0
    fi
    sleep 0.5
  done
  echo "servers did not come up. logs:" >&2
  tail -20 /tmp/seoq-serve.log /tmp/seoq-app.log >&2
  return 1
}

stop_servers() {
  [ -n "${SERVE_PID:-}" ] && kill $SERVE_PID 2>/dev/null
  [ -n "${APP_PID:-}" ] && kill $APP_PID 2>/dev/null
  kill_port 5199; kill_port 5203
  return 0
}
trap stop_servers EXIT

pass=0; fail=0; failed=""
run_one() {
  local f="$1" runner="$2"
  if out=$(timeout 150 $runner "$f" 2>&1); then
    pass=$((pass+1))
  else
    fail=$((fail+1)); failed="$failed $f"
    echo "--- FAIL $f"; echo "$out" | tail -15 | sed 's/^/    /'
  fi
}

case "$WHAT" in
  py)  for f in tests/*_test.py; do run_one "$f" "$PY"; done ;;
  js)  start_servers || exit 1; for f in tests/*_test.js; do run_one "$f" node; done ;;
  all) for f in tests/*_test.py; do run_one "$f" "$PY"; done
       start_servers || exit 1
       for f in tests/*_test.js; do run_one "$f" node; done ;;
  *)   [ -f "$WHAT" ] || { echo "no such test: $WHAT" >&2; exit 1; }
       case "$WHAT" in
         *.js) start_servers || exit 1; run_one "$WHAT" node ;;
         *.py) run_one "$WHAT" "$PY" ;;
         *) echo "not a test file: $WHAT" >&2; exit 1 ;;
       esac ;;
esac

echo
echo "PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ] || { echo "failed:$failed"; exit 1; }
