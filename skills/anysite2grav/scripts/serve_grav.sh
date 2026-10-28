#!/usr/bin/env bash
# Run Grav with PHP's built-in server (development only).
#
# Usage: serve_grav.sh <project-dir> start|stop|status|restart [--port 8000] [--host 127.0.0.1]
#
# Writes the PID and log under <project>/.local/. Prints the site, Admin and API URLs.
set -euo pipefail

[ $# -ge 2 ] || { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
project="$(cd "$1" && pwd)"; action="$2"; shift 2
port=8000; host=127.0.0.1
while [ $# -gt 0 ]; do
  case "$1" in
    --port) port="$2"; shift 2 ;;
    --host) host="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

state="$project/.local"
mkdir -p "$state"
pidfile="$state/server.pid"
portfile="$state/server.port"
log="$state/server.log"

running() { [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; }

start() {
  if running; then
    echo "already running (pid $(cat "$pidfile")) on http://$host:$(cat "$portfile")"
    return
  fi
  if lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $port is in use; pass --port" >&2
    exit 1
  fi
  (cd "$project/grav" && nohup php -S "$host:$port" system/router.php >"$log" 2>&1 & echo $! >"$pidfile")
  echo "$port" >"$portfile"
  for _ in $(seq 1 40); do
    if curl -fs -o /dev/null "http://$host:$port/"; then break; fi
    sleep 0.25
  done
  echo "site  http://$host:$port/"
  echo "admin http://$host:$port/admin"
  echo "api   http://$host:$port/api/v1"
}

stop() {
  if running; then kill "$(cat "$pidfile")"; rm -f "$pidfile"; echo "stopped"; else echo "not running"; fi
}

case "$action" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) if running; then echo "running pid $(cat "$pidfile") port $(cat "$portfile")"; else echo "stopped"; fi ;;
  *) echo "unknown action $action" >&2; exit 2 ;;
esac
