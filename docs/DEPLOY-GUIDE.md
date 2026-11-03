# ISMAS Deploy Guide (VPS + Tailscale)

This guide sets up the ISMAS **brain** (n8n + Postgres) on a VPS and installs the **agent** on the servers you want to monitor.
All traffic stays inside your Tailscale network (tailnet), so no public ports or domain are needed.

```
 monitored server (agent) ──HTTPS over tailnet──► VPS: tailscale serve → n8n ─► Postgres
                                                                  │
                                                                  └─► DeepSeek ─► Telegram
```

## 0. What you need

- A VPS with Docker + Docker Compose and Tailscale installed and connected.
- Every monitored server also on the same tailnet.
- A DeepSeek API key.
- A Telegram bot token (from @BotFather) and your chat ID.
- This repo pushed to git, with your latest changes committed.

---

## 1. Enable HTTPS in Tailscale (once)

1. Open https://login.tailscale.com/admin/dns
2. Turn on **MagicDNS**.
3. Under **HTTPS Certificates**, click **Enable HTTPS**.

Get the VPS's full name on the VPS:

```bash
tailscale status --self --json | grep '"DNSName"' | head -1


```

It looks like `myvps.tail1234.ts.net.` — drop the trailing dot. This is your `TS_HOSTNAME`.

## 2. Get the n8n version you tested

On your **local machine** (where the lab runs):

```bash
docker exec n8n-local n8n --version
```

Keep this number. It pins the production n8n so an update can't break the workflows.

## 3. Start the brain on the VPS

```bash
git clone <your-repo-url> ismas
cd ismas/deploy/brain
cp .env.example .env
nano .env
```

Fill in `.env`:

| Variable | Value |
|---|---|
| `TS_HOSTNAME` | the name from step 1, no trailing dot |
| `N8N_VERSION` | the version from step 2 |
| `AGENT_TOKEN` | `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | `openssl rand -hex 32` (a different value) |
| `TELEGRAM_CHAT_ID` | your chat ID |

Save the `AGENT_TOKEN`. Every agent needs the same value.

Then start it:

```bash
docker compose up -d
docker compose ps                        # postgres must be "healthy"
sudo tailscale serve --bg 5678           # publishes n8n over HTTPS inside the tailnet
tailscale serve status
```

Check the ISMAS tables exist:

```bash
docker exec -it ismas-postgres psql -U ismas -d ismas -c '\dt'
```

You should see `servers`, `payloads`, `events`, `incidents`.

> If the tables are missing, the init SQL only runs on a fresh volume:
> `docker compose down -v && docker compose up -d` (this deletes all data).

## 4. Set up n8n

Open `https://<TS_HOSTNAME>` from any device on your tailnet.

1. Create the owner account.
2. Create three credentials (Overview → Credentials):

   | Name | Type | Settings |
   |---|---|---|
   | **ISMAS Postgres** | Postgres | Host `postgres` · DB `ismas` · User `ismas` · Password = `POSTGRES_PASSWORD` · Port `5432` · SSL Disable |
   | **DeepSeek** | Header Auth | Name `Authorization` · Value `Bearer sk-xxxxx` |
   | **ISMAS Telegram** | Telegram API | Access token from BotFather |

3. Import both workflows from `n8n-local/workflows/`:
   - `A-ismas-ingest-analyze.json`
   - `B-ismas-watchdog.json`
4. Open each workflow and check every node that uses a credential points at the ones above.
5. **Activate** both workflows.

Test the webhook:

```bash
# wrong token → expect 401
curl -i -X POST https://<TS_HOSTNAME>/webhook/ismas-ingest -H 'Content-Type: application/json' -d '{}'
```

If you get a 404, Workflow A isn't active yet (or you used the `/webhook-test/` URL).

## 5. Add a config for each monitored server

The agent picks `agent/configs/<SERVER_NAME>.yaml`. Without one, it falls back to `default.yaml`, which only reads syslog and auth.log.

Create `agent/configs/web-01.yaml` (use your own name and paths):

```yaml
batch_interval: 30
processes: [nginx, php-fpm]
logs:
  - { path: /var/log/nginx/access.log, type: nginx_access, source: nginx_access }
  - { path: /var/log/nginx/error.log,  type: generic,      source: nginx_error }
disk_paths: [/]
```

Log `type` values in use: `nginx_access`, `app_json`, `generic`.
Commit and push the config so you can pull it on the server.

## 6. Install the agent on each monitored server

Run this on every server you want to monitor (it must be on the tailnet):

```bash
git clone <your-repo-url> ismas && cd ismas
sudo ./deploy/agent/install.sh web-01 https://<TS_HOSTNAME>/webhook/ismas-ingest <AGENT_TOKEN>
journalctl -u ismas-agent -f
```

The first name must match the config file name (`web-01.yaml`).

The agent starts in **dry-run mode** and only prints payloads. When they look right:

```bash
sudo sed -i 's/AGENT_DRY_RUN=1/AGENT_DRY_RUN=0/' /etc/ismas-agent.env
sudo systemctl restart ismas-agent
```

Within about 30 seconds the server should appear in the `servers` table:

```bash
docker exec -it ismas-postgres psql -U ismas -d ismas -c 'select * from servers;'
```

## 7. Verify end to end

1. **Heartbeat:** the server shows `up` with a recent `last_seen`.
2. **Alert:** on a monitored server, stop a service listed in `processes` (e.g. `sudo systemctl stop nginx` for 1 minute). A Telegram alert should arrive. Start it again and expect no more alerts.
3. **Watchdog:** `sudo systemctl stop ismas-agent`. After the watchdog interval the server should be marked `down` with a Telegram message. Start the agent and expect a "recovered" message.

---

## Day-to-day

```bash
# VPS
docker compose logs -f n8n               # n8n logs
docker compose pull && docker compose up -d   # only after changing N8N_VERSION

# Monitored server
systemctl status ismas-agent
journalctl -u ismas-agent -n 50
```

Update the agent after code changes: `git pull && sudo ./deploy/agent/install.sh ...` (same arguments).

## Backups

- Back up the Postgres volume and the n8n volume. Quick database dump:
  ```bash
  docker exec ismas-postgres pg_dumpall -U ismas > ismas-backup-$(date +%F).sql
  ```
- Export the workflows from n8n after you change them, and commit the JSON to `n8n-local/workflows/`.
- The n8n encryption key lives in the `n8n_data` volume. Without it, saved credentials can't be decrypted after a restore.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `tailscale serve` says HTTPS is not enabled | Enable HTTPS Certificates in the admin DNS page (step 1) |
| Agent logs `send failed ... buffering` | Wrong URL, workflow not active, or the server isn't on the tailnet. Test with `curl` from that server |
| Webhook returns 401 | `AGENT_TOKEN` on the agent differs from the one in the brain's `.env` |
| Webhook returns 404 | Workflow A is not activated, or the path isn't `ismas-ingest` |
| `docker compose up` fails with "set in .env" | A required variable in `.env` is empty |
| n8n login loops or shows a cookie error | `TS_HOSTNAME` is wrong, or you opened it by IP instead of the HTTPS name |
| No Telegram message | Check the Telegram credential, `TELEGRAM_CHAT_ID`, and that you pressed Start on your bot |
| Code nodes fail on `$env` | `N8N_BLOCK_ENV_ACCESS_IN_NODE` must be `"false"` in the compose file |

## Security checklist

- [ ] `.env` and `/etc/ismas-agent.env` are not committed and not world-readable
- [ ] Strong random `AGENT_TOKEN` and `POSTGRES_PASSWORD`
- [ ] Postgres is not published on any port
- [ ] n8n is reachable only through the tailnet
- [ ] n8n version is pinned
- [ ] You are OK with log excerpts being sent to DeepSeek (IPs and emails are hashed first)
