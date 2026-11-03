#!/usr/bin/env bash
# ISMAS chaos runner — break things on purpose, then show what ISMAS detected.
# Usage: ./chaos/run.sh <scenario>      (./chaos/run.sh help)
set -u

WEB=sim-web
DB=sim-db
PG=ismas-postgres
URL=http://localhost:8081
SETTLE=${SETTLE:-45}          # seconds to wait for AI/alerts before the report

# ---------- pretty output ----------
c_b=$'\e[1m'; c_r=$'\e[31m'; c_g=$'\e[32m'; c_y=$'\e[33m'; c_c=$'\e[36m'; c_0=$'\e[0m'
ts()     { date +%H:%M:%S; }
title()  { echo; echo "${c_b}${c_c}══════ $* ══════${c_0}"; }
step()   { echo "${c_y}[$(ts)]${c_0} $*"; }
expect() { echo "${c_g}  ✔ expect:${c_0} $*"; }
fail()   { echo "${c_r}✘ $*${c_0}"; exit 1; }

countdown() {  # countdown <seconds> <label>
  local s=$1
  while [ "$s" -gt 0 ]; do printf "\r  ⏳ %s… %3ss " "$2" "$s"; sleep 1; s=$((s-1)); done
  printf "\r%60s\r" ""
}

psql_q() { docker exec "$PG" psql -U ismas -d ismas -q -X -c "$1"; }

precheck() {
  for c in $WEB $DB $PG n8n-local; do
    [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" = "true" ] \
      || fail "container '$c' is not running (cd simulated-servers && docker compose up -d)"
  done
}

report() {  # report <start_iso>
  step "waiting ${SETTLE}s for agents → n8n → AI → Telegram…"
  countdown "$SETTLE" "settling"
  title "What ISMAS recorded since $(date -d "$1" +%H:%M:%S)"
  psql_q "SELECT to_char(created_at,'HH24:MI:SS') AS time, severity, alerted AS tg,
                 confidence AS conf, left(title, 70) AS title
          FROM incidents WHERE created_at >= '$1' ORDER BY id;"
  psql_q "SELECT server, level, sum(count) AS hits, left(min(message), 60) AS sample
          FROM events WHERE received_at >= '$1' AND level IN ('error','critical')
          GROUP BY server, level, left(message, 40) ORDER BY hits DESC LIMIT 8;"
  echo "Compare with your Telegram. No incident? Check n8n → Executions."
}

# ---------- scenarios ----------
s_db_down() {
  title "DB DOWN — database crashes, web app starts failing"
  expect "fast alert from sim-web: Database connection failed (correlated)"
  expect "~90-150s: 🔴 sim-db stopped reporting (watchdog)"
  expect "after restart: ✅ sim-db is back online"
  step "docker stop $DB"; docker stop "$DB" >/dev/null
  for i in $(seq 1 15); do
    curl -s -o /dev/null "$URL/db"; printf "\r  web → /db request %2s/15 (every 10s)" "$i"; sleep 10
  done; echo
  step "docker start $DB"; docker start "$DB" >/dev/null
  countdown 40 "waiting for sim-db agent to report again"
}

s_error_flood() {
  title "ERROR FLOOD — 200× HTTP 500 in ~60s"
  expect "one grouped incident (count ≈ 200), not 200 alerts"
  for i in $(seq 1 200); do
    curl -s -o /dev/null "$URL/error"; [ $((i % 20)) -eq 0 ] && printf "\r  sent %3s/200" "$i"; sleep 0.3
  done; echo
}

s_cpu_spike() {
  title "CPU SPIKE — busy loop on sim-web for 75s (limit 0.5 CPU)"
  expect "metrics: CPU usage critical (~100% of container limit)"
  step "starting busy loop"
  docker exec -d "$WEB" timeout 75 sh -c 'while :; do :; done'
  countdown 80 "burning CPU"
}

s_memory_leak() {
  title "MEMORY LEAK — grow memory on sim-web to ~96% of 256MB, hold 70s"
  expect "metrics: Memory usage critical (or OOM kill of the leaking process)"
  docker exec -d "$WEB" python3 -c '
import time
def r(p): return open(p).read().strip()
mx = int(r("/sys/fs/cgroup/memory.max"))
def used():
    st = r("/sys/fs/cgroup/memory.stat").splitlines()
    ina = next(int(l.split()[1]) for l in st if l.startswith("inactive_file "))
    return int(r("/sys/fs/cgroup/memory.current")) - ina
blocks, total = [], 0
while used() / mx < 0.96 and total < mx * 0.95:
    blocks.append(b"\x01" * (4 * 1024 * 1024)); total += 4 * 1024 * 1024
    time.sleep(0.3)
time.sleep(70)'
  countdown 95 "leaking memory"
}

s_disk_fill() {
  title "DISK FULL — fill /data (64MB) to ~97% for 70s"
  expect "metrics: Disk /data usage critical"
  step "writing 62MB to /data/fill"
  docker exec "$WEB" sh -c 'dd if=/dev/zero of=/data/fill bs=1M count=62 2>/dev/null; df -h /data | tail -1'
  countdown 70 "disk full"
  step "cleanup: rm /data/fill"; docker exec "$WEB" rm -f /data/fill
}

s_slow_db() {
  title "SLOW DB — long queries (12s) + slow web requests"
  expect "sim-db: Slow query critical (≥10s) · sim-web: slow requests (correlated)"
  step "4× SELECT SLEEP(12) on sim-db + 10× /db-slow on sim-web"
  for i in 1 2 3 4; do
    docker exec "$DB" mariadb -uapp -papppass -e "SELECT SLEEP(12)" >/dev/null 2>&1 &
  done
  for i in $(seq 1 10); do curl -s -o /dev/null "$URL/db-slow" & done
  wait
  countdown 30 "waiting for next batch"
}

s_nginx_down() {
  title "NGINX DOWN — web server process stops for 45s"
  expect "🔴 Process nginx is not running (within ~10s)"
  step "supervisorctl stop nginx"; docker exec "$WEB" supervisorctl stop nginx || fail "supervisorctl failed (rebuild sim-web)"
  countdown 45 "nginx down"
  step "supervisorctl start nginx"; docker exec "$WEB" supervisorctl start nginx
  countdown 35 "waiting for recovery batch"
}

s_reset() {
  title "RESET — clear incidents (n8n dedup) + restart agents (60s cooldown)"
  psql_q "DELETE FROM incidents;"
  docker exec "$WEB" supervisorctl restart agent || fail "supervisorctl failed (rebuild sim-web)"
  docker exec "$DB" python3 -c 'import os,signal
for p in filter(str.isdigit, os.listdir("/proc")):
    try:
        if b"agent.py" in open(f"/proc/{p}/cmdline","rb").read(): os.kill(int(p), signal.SIGTERM)
    except OSError: pass'
  step "done — agents restart within ~5s"
}

s_all() {
  title "FULL DEMO — all scenarios, 60s gap between each"
  s_reset; sleep 10
  for s in nginx_down error_flood cpu_spike memory_leak disk_fill slow_db db_down; do
    "s_$s"; countdown 60 "cooldown before next scenario"
  done
}

usage() {
  cat <<EOF
${c_b}ISMAS chaos runner${c_0}
  ./chaos/run.sh <scenario>

  db-down       stop DB → web errors → down alert → recovery     (~4 min)
  error-flood   200× HTTP 500 in ~60s (tests grouping)          (~2 min)
  cpu-spike     CPU 100% on sim-web for 75s                     (~2 min)
  memory-leak   RAM to ~96% on sim-web for 70s                  (~2.5 min)
  disk-fill     /data to ~97% for 70s                           (~2 min)
  slow-db       12s queries + slow web requests                 (~1.5 min)
  nginx-down    stop nginx process for 45s                      (~2 min)
  reset         clear incidents + restart agents (before a demo)
  all           reset + every scenario in sequence              (~25 min)

  SETTLE=60 ./chaos/run.sh db-down   # wait longer before report
EOF
}

# ---------- main ----------
sc=${1:-help}
case "$sc" in
  help|-h|--help|"") usage; exit 0 ;;
esac
fn="s_${sc//-/_}"
declare -F "$fn" >/dev/null || { usage; fail "unknown scenario: $sc"; }

precheck
START=$(date -Iseconds)
"$fn"
[ "$sc" != "reset" ] && report "$START"
