# ISMAS — Intelligent Server Monitoring & Alert System

ISMAS watches servers, filters their logs and metrics, and uses an AI model to explain
problems (root cause, fix steps, severity). It then sends the alert to Telegram.
It also notices when a server goes silent.

**Status:** working prototype. It runs locally in Docker (WSL) with two fake servers.
Nothing is deployed to a real server or VPS yet. See [Moving to a real server](#moving-to-a-real-server).

---

## How it works

```
 ┌──────────────┐   ┌──────────────┐
 │  sim-web     │   │  sim-db      │      (later: your real servers)
 │ nginx + PHP  │   │  MariaDB     │
 │ + ISMAS agent│   │ + ISMAS agent│
 └──────┬───────┘   └──────┬───────┘
        │   HTTPS POST JSON (ismas.v1, token-authenticated)
        └─────────┬────────┘
                  ▼
        ┌───────────────────┐
        │ n8n  (the "brain")│
        │ A: Ingest+Analyze │──► Postgres (servers, payloads, events, incidents)
        │ B: Watchdog       │──► DeepSeek AI ──► Telegram alert
        └───────────────────┘
```

1. **Agent** (Python, runs on every monitored server)
   - Tails log files and keeps only warning-level and above.
   - Masks IPs and emails (hashed).
   - Groups repeated events by signature.
   - Collects CPU, memory and disk metrics, and checks that required processes are running.
   - Sends a **batch** every `batch_interval` seconds (default 30). The batch also acts as a heartbeat.
   - Sends **critical** events immediately, with a cooldown so the same event isn't re-sent.
   - If the server can't be reached, it buffers payloads to disk and resends them later.
2. **n8n Workflow A: Ingest & Analyze**
   - Webhook → validate token → store in Postgres → skip duplicates → build prompt → DeepSeek → parse the answer → save the incident → Telegram alert.
   - It sends a "recovered" message when a server that was down comes back.
3. **n8n Workflow B: Watchdog**
   - Marks servers as `down` when their heartbeat stops.
   - Runs a daily retention cleanup.
4. **Postgres** holds n8n's own data (DB `n8n`) and ISMAS data (DB `ismas`).

---

## Repo layout

| Path | What it is |
|---|---|
| `agent/` | The monitoring agent. `agent.py` is the entry point and `ismas_agent/` holds the modules (`tailer`, `parsers`, `processor`, `metrics`, `sender`, `config`). |
| `agent/configs/` | Per-server YAML configs, picked by `SERVER_NAME`. `default.yaml` is the fallback for a real Linux box. |
| `simulated-servers/` | Docker Compose lab: `sim-web`, `sim-db`, `postgres` and `n8n`. |
| `simulated-servers/postgres/init/` | SQL that creates the `ismas` DB and the tables `servers`, `payloads`, `events`, `incidents`. |
| `n8n-local/workflows/` | Exported workflows: `A-ismas-ingest-analyze.json` and `B-ismas-watchdog.json`. |
| `n8n-local/code-nodes/`, `n8n-local/sql/` | Scripts and SQL used by the n8n nodes. |
| `chaos/` | `run.sh` breaks things on purpose to test detection. |
| `docs/PHASE5-GUIDE.md` | Step-by-step guide for building the n8n workflows by hand. |

---

## Requirements

- Docker + Docker Compose
- A **Telegram bot** token (from @BotFather) and your chat ID
- A **DeepSeek** API key
- Agent only: Python 3.9+, `psutil`, `PyYAML` (`agent/requirements.txt`)

---

## Run the lab (local)

```bash
cd simulated-servers
cp .env.example .env     # set AGENT_TOKEN, POSTGRES_PASSWORD, TELEGRAM_CHAT_ID
docker compose up -d --build
docker compose ps        # postgres should be "healthy"
```

Then:

1. Open n8n at http://localhost:5678 and create the owner account.
2. Create three credentials: **ISMAS Postgres**, **DeepSeek** (Header Auth, `Authorization: Bearer sk-...`) and **ISMAS Telegram**.
3. Import both workflows from `n8n-local/workflows/` and activate them.
   Node names matter, so keep them as they are. `docs/PHASE5-GUIDE.md` explains each node.
4. Check the tables: `docker exec -it ismas-postgres psql -U ismas -d ismas -c '\dt'`

| Service | URL / port |
|---|---|
| sim-web (nginx + PHP) | http://localhost:8081 |
| n8n | http://localhost:5678 |
| Postgres | localhost:5433 |
| sim-db (MariaDB) | localhost:3307 |

> If the ISMAS tables are missing, the init SQL only runs on a fresh volume.
> Fix: `docker compose down && docker volume rm ismas-lab_pg_data && docker compose up -d`

Until Workflow A is active, the agents get 404s and buffer to disk. This is expected.

---

## Test with chaos scenarios

```bash
./chaos/run.sh help
./chaos/run.sh reset         # before a demo
./chaos/run.sh db-down
./chaos/run.sh all           # full run, about 25 min
```

| Scenario | What it does |
|---|---|
| `db-down` | Stops the DB, so web errors, a down alert and then recovery |
| `error-flood` | 200 HTTP 500s in about 60s (tests grouping) |
| `cpu-spike` | CPU at 100% for 75s |
| `memory-leak` | RAM at about 96% for 70s |
| `disk-fill` | `/data` at about 97% for 70s |
| `slow-db` | 12s queries and slow web requests |
| `nginx-down` | Stops nginx for 45s |

Each scenario prints what ISMAS should detect, breaks something, recovers, waits
(`SETTLE=45` by default), then prints the incidents ISMAS recorded.

---

## Agent configuration

Defaults are in `agent/ismas_agent/config.py`, and a per-server YAML overrides them.

```yaml
batch_interval: 30
processes: [nginx, php-fpm]
logs:
  - { path: /var/log/nginx/access.log, type: nginx_access, source: nginx_access }
  - { path: /var/log/app/app.log,      type: app_json,     source: app }
disk_paths: [/]
```

Environment variables used by the agent: `SERVER_NAME`, `INGEST_URL`, `AGENT_TOKEN`,
`AGENT_DRY_RUN` (`1` only prints payloads), `AGENT_CONFIG`.

Default thresholds (warn / critical):
- CPU: 80 / 95
- Memory: 85 / 95
- Disk: 85 / 95
- Slow request: 2s
- Slow query (critical): 10s

---

## Moving to a real server

Not set up yet. This is the plan:

### 1. Brain server (VPS)
1. Install Docker and Compose.
2. Copy `simulated-servers/docker-compose.yml`. Keep only `postgres` and `n8n`, and drop `sim-web` and `sim-db`.
3. Change the n8n settings for production:
   - Put it behind HTTPS (Caddy or Nginx with a Let's Encrypt cert).
   - Remove `N8N_SECURE_COOKIE: "false"`.
   - Set `WEBHOOK_URL` to your public domain.
   - Don't publish the Postgres port (`5433`) to the internet.
4. Create a **strong, random** `AGENT_TOKEN` and `POSTGRES_PASSWORD` in `.env`. Never commit `.env`.
5. Import and activate the workflows, then set up the credentials.
6. Open only ports 80 and 443 in the firewall.

### 2. Each monitored server
```bash
sudo mkdir -p /opt/ismas && sudo cp -r agent /opt/ismas/
cd /opt/ismas/agent
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
- Create `configs/<hostname>.yaml` with that server's logs, processes and disks. Or set `SERVER_NAME` and `AGENT_CONFIG`.
- Set the env vars: `INGEST_URL=https://your-domain/webhook/ismas-ingest`, `AGENT_TOKEN=<same token>`, `SERVER_NAME=<name>`.
- Run it as a systemd service so it restarts on failure:
  ```ini
  # /etc/systemd/system/ismas-agent.service
  [Unit]
  Description=ISMAS agent
  After=network-online.target

  [Service]
  EnvironmentFile=/etc/ismas-agent.env
  ExecStart=/opt/ismas/agent/.venv/bin/python /opt/ismas/agent/agent.py
  Restart=always

  [Install]
  WantedBy=multi-user.target
  ```
- Make sure `/var/lib/ismas-agent/` exists and is writable (the disk buffer lives there).
- Try `AGENT_DRY_RUN=1` first, then switch it to `0`.

### 3. Verify
- Run `curl -X POST` against the webhook with a wrong token. It should return 401.
- Run `./chaos/run.sh`-style tests (stop a service) and confirm the Telegram alert arrives.
- Stop the agent and confirm Workflow B marks the server `down`.

---

## Security notes

- `AGENT_TOKEN` authenticates agents, so use a long random value in production.
- IPs and emails are hashed before they leave the server. Review the `mask` config for anything else sensitive in your logs.
- The lab uses throwaway passwords (`rootpass`, `apppass`, `ismas-dev-pass`). Change all of them on a real server.
- Log excerpts are sent to a third-party AI (DeepSeek). Check this is acceptable for your data.

---

## Known gaps / ideas

- The sim-db Dockerfile is committed twice (`DockerFile` and `Dockerfile`). Delete one.
- There is no tests folder. The chaos runner is the only test.
- There is no dashboard. Incidents are only in Postgres and Telegram.
- The agent has no packaged installer yet (a script or `.deb`).
