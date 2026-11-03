# Chaos scenarios

Run from the repo root (WSL), with the stack + n8n workflows active:

```bash
./chaos/run.sh help
./chaos/run.sh reset        # before a demo: clear dedup + agent cooldowns
./chaos/run.sh db-down
./chaos/run.sh all          # full ~25 min demo
```

Each scenario: prints what ISMAS *should* detect → breaks something → recovers →
waits `SETTLE` seconds → prints incidents + events ISMAS actually recorded.
