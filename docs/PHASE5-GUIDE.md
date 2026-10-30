# ISMAS Phase 5 — n8n Brain (Build Guide)

Two workflows:
- **A · Ingest & Analyze**: receive agent data → store → AI → alert
- **B · Watchdog**: detect silent servers (heartbeat) + daily cleanup

All SQL is in `n8n-local/sql/`, all Code node scripts in `n8n-local/code-nodes/`. Copy-paste them; don't retype.

> **Node names matter.** Code nodes reference other nodes by name (e.g. `$('Validate')`). Use the names exactly as written here.

---

## 0. Start the stack

```bash
cd ~/workspace/ismas/simulated-servers
cp .env.example .env          # set AGENT_TOKEN, TELEGRAM_CHAT_ID
docker compose up -d --build
docker compose ps             # postgres must be "healthy"
```

- n8n now uses Postgres, so you'll create a **new owner account** at http://localhost:5678.
- Check the ISMAS tables exist:
  ```bash
  docker exec -it ismas-postgres psql -U ismas -d ismas -c '\dt'
  ```
  You should see `servers`, `payloads`, `events`, `incidents`.
- If the tables are missing: the init script only runs on a **fresh** volume →
  `docker compose down && docker volume rm ismas-lab_pg_data && docker compose up -d`

> Agents now send for real (`AGENT_DRY_RUN=0`). Until Workflow A is active they get 404 and **buffer to disk** — that's expected, they'll resend later.

---

## 1. Credentials (n8n → Overview → Credentials → Create)

| Name | Type | Settings |
|---|---|---|
| **ISMAS Postgres** | Postgres | Host `postgres` · Database `ismas` · User `ismas` · Password (from .env) · Port `5432` · SSL `Disable` |
| **DeepSeek** | Header Auth | Name `Authorization` · Value `Bearer sk-xxxxx` |
| **ISMAS Telegram** | Telegram API | Access Token = BotFather token |

---

## 2. Workflow A · "ISMAS Ingest & Analyze"

### Flow
```
Webhook → Validate → Is Valid? ─false→ Reject (401)
                               └true→ Accept (200) → Store ─┬→ Was Down? ─true→ Recovered Msg → Telegram Recovered
                                                            └→ Needs AI? ─true→ Context → Not Duplicate? ─true→
                                                               Build Prompt → DeepSeek → Parse AI → Save Incident →
                                                               Should Alert? ─true→ Telegram Alert
```

### Nodes

**1. Webhook** — node name `Webhook`
- HTTP Method: `POST`
- Path: `ismas-ingest`
- Authentication: `None` (we check the token ourselves)
- Respond: **Using 'Respond to Webhook' Node**

**2. Code** — name `Validate`
- Mode: Run Once for All Items
- Paste `code-nodes/A1-validate.js`
- Output: `valid`, `needs_ai`, `signature`, `fresh_events`, `payload`

**3. If** — name `Is Valid?`
- Condition: `{{ $json.valid }}` · Boolean · **is true**

**4. Respond to Webhook** (false branch) — name `Reject`
- Respond With: JSON · Body `{"ok": false, "error": "unauthorized"}`
- Options → Response Code: `401`
- (End of false branch.)

**5. Respond to Webhook** (true branch) — name `Accept`
- Respond With: JSON · Body `{"ok": true}`
- Responding early = agent isn't kept waiting for the AI (n8n keeps running the rest).

**6. Postgres** — name `Store`
- Credential: ISMAS Postgres · Operation: **Execute Query**
- Query: paste `sql/A-store.sql`
- Options → Query Parameters: `{{ [ JSON.stringify($('Validate').first().json) ] }}`
- Output: `prev_status`, `payload_id`, `events_stored`, `server`

> Why one JSON parameter? Log messages contain commas and quotes. Passing everything as one JSON string avoids comma-splitting bugs **and** SQL injection.

Connect `Store` to **two** nodes (drag two lines out of its output):

**7a. If** — name `Was Down?`
- Condition: `{{ $json.prev_status }}` · String · **is equal to** `down`

**8a. Code** (true) — name `Recovered Msg`
```js
return [{ json: { telegram_text: `✅ <b>${$json.server} is back online</b>\nAgent reporting again.` } }];
```

**9a. Telegram** — name `Telegram Recovered`
- Credential: ISMAS Telegram · Operation: Send Message
- Chat ID: `{{ $env.TELEGRAM_CHAT_ID }}`
- Text: `{{ $json.telegram_text }}`
- Additional Fields → Parse Mode: `HTML` · Append n8n Attribution: **off**

**7b. If** — name `Needs AI?`
- Condition: `{{ $('Validate').first().json.needs_ai }}` · Boolean · **is true**

**8b. Postgres** (true) — name `Context`
- Execute Query · paste `sql/A-context.sql`
- Query Parameters: `{{ [ $('Validate').first().json.signature ] }}`
- Output: `recent_dupes`, `recent_events` (all servers, last 5 min), `servers` (status + seconds since last report)

**9b. If** — name `Not Duplicate?`
- Condition: `{{ $json.recent_dupes }}` · Number · **is equal to** `0`
- Same problem analyzed in last 15 min → stop (saves AI calls).

**10. Code** (true) — name `Build Prompt`
- Paste `code-nodes/A2-build-prompt.js`

**11. HTTP Request** — name `DeepSeek`
- Method `POST` · URL `https://api.deepseek.com/chat/completions`
- Authentication: Generic Credential Type → **Header Auth** → DeepSeek
- Send Body: on · Body Content Type: JSON · Specify Body: **Using JSON**
- JSON: `{{ JSON.stringify($json.body) }}`
- Options → Timeout: `60000`
- Node **Settings** tab → Retry On Fail: on · Max Tries `2` · Wait `3000`

**12. Code** — name `Parse AI`
- Paste `code-nodes/A3-parse-ai.js`
- If the AI returns broken/empty JSON, a fallback incident is created — you never lose an alert.

**13. Postgres** — name `Save Incident`
- Execute Query · paste `sql/A-save-incident.sql`
- Query Parameters: `{{ [ JSON.stringify($('Parse AI').first().json) ] }}`

**14. If** — name `Should Alert?`
- Condition: `{{ $('Parse AI').first().json.should_alert }}` · Boolean · **is true**
- Only `high` / `critical` alert. Lower severities are saved for daily reports (Phase 7).

**15. Telegram** (true) — name `Telegram Alert`
- Same settings as `Telegram Recovered`
- Text: `{{ $('Parse AI').first().json.telegram_text }}`

**Save → Activate / Publish** the workflow (top right).
Production URL = `http://n8n:5678/webhook/ismas-ingest` (what agents use). The **Test URL** (`/webhook-test/...`) only works while you click "Listen for test event".

---

## 3. Workflow B · "ISMAS Watchdog"

```
Every Minute → Mark Down → Down Message → Telegram Down
Daily 3AM    → Retention
```

**1. Schedule Trigger** — name `Every Minute` · Interval: Minutes · `1`

**2. Postgres** — name `Mark Down`
- Execute Query · paste `sql/B-mark-down.sql` (no parameters)
- Marks servers silent >90s as `down` (3 missed batches) + logs a critical incident
- Only returns servers that **just** went down → one alert per outage, not every minute

**3. Code** — name `Down Message` · paste `code-nodes/B1-down-message.js`

**4. Telegram** — name `Telegram Down`
- Text: `{{ $json.telegram_text }}` · Chat ID / Parse Mode as before

**5. Schedule Trigger** (second trigger, same workflow) — name `Daily 3AM` · Days · Hour `3`

**6. Postgres** — name `Retention` · paste `sql/B-retention.sql` (deletes raw data >7 days, keeps incidents)

**Save → Activate / Publish.**

---

## 4. Test scenarios

Watch: n8n → **Executions** tab, and your Telegram.

| # | Do this | Expect |
|---|---|---|
| 1 | wait 30s | Batches arrive every 30s per server · no Telegram |
| 2 | `docker exec -it ismas-postgres psql -U ismas -d ismas -c "select * from servers"` | `sim-web`, `sim-db` = up |
| 3 | `curl localhost:8081/crash` | Telegram 🟠/🔴 PHP fatal error analysis |
| 4 | `for i in $(seq 10); do curl -s localhost:8081/error; done` | One alert (or none if AI says medium) · repeat within 15 min → no new alert |
| 5 | `docker stop sim-db` then `curl localhost:8081/db` a few times | Fast alert: DB connection failed on sim-web · ~90s later: 🔴 **sim-db stopped reporting** |
| 6 | `docker start sim-db` | ✅ **sim-db is back online** |
| 7 | `curl -X POST localhost:5678/webhook/ismas-ingest -H 'X-ISMAS-Token: wrong' -d '{}'` | `401 unauthorized` |
| 8 | Stop Workflow A for 2 min, then re-activate | Agents resend buffered payloads (`resent: true`) |

Look at AI results:
```bash
docker exec -it ismas-postgres psql -U ismas -d ismas -c \
 "select id, created_at, severity, title, confidence from incidents order by id desc limit 10"
```

---

## 5. Troubleshooting

| Problem | Fix |
|---|---|
| Agent log: `send failed (HTTP Error 404)` | Workflow A not active, or path ≠ `ismas-ingest` |
| `$env is not defined` / access denied | `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` missing → `docker compose up -d n8n` |
| Postgres: "there is no parameter $1" | Query Parameters empty — use the `{{ [ ... ] }}` array form exactly |
| Postgres: "relation servers does not exist" | Credential points to DB `n8n` instead of `ismas` |
| DeepSeek 401 | Header value must be `Bearer sk-...` (with the space) |
| Telegram "can't parse entities" | Parse Mode must be `HTML` (code already escapes `<`, `>`, `&`) |
| Telegram "chat not found" | Send any message to your bot first; re-check chat id |
| Every alert is "Unanalyzed …" | AI returned empty content — check DeepSeek node output; retry is enabled |

---

## 6. Notes

- **Privacy:** DeepSeek processes data on its own servers. The agent already masks IPs, emails and secrets. For client/government servers later, consider a local model (Ollama) as a "privacy mode".
- **Cost:** only new error/critical events reach the AI, deduped for 15 min. Expect a handful of calls per hour during testing.
- **Export your workflows** when done: Workflow → ⋯ → Download → save into `n8n-local/workflows/` and commit (remove credentials IDs if sharing publicly).
