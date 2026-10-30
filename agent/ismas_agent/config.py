import os, socket
import yaml

DEFAULTS = {
    "batch_interval": 30,          # seconds between normal batches (also acts as heartbeat)
    "tick": 2,                     # seconds between log reads
    "process_check_interval": 10,
    "critical_cooldown": 60,       # same critical event won't fast-send again within this window
    "max_events_per_batch": 50,
    "thresholds": {
        "cpu_warn": 80, "cpu_crit": 95,
        "mem_warn": 85, "mem_crit": 95,
        "disk_warn": 85, "disk_crit": 95,
        "slow_request_s": 2.0,
        "slow_query_crit_s": 10.0,
    },
    "processes": [],
    "logs": [],
    "mask": {"hash_ips": True, "hash_emails": True},
    "buffer_path": "/var/lib/ismas-agent/buffer.jsonl",
    "buffer_max_lines": 2000,
}


def _merge(base, extra):
    out = dict(base)
    for k, v in (extra or {}).items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    name = os.getenv("SERVER_NAME") or socket.gethostname()
    path = os.getenv("AGENT_CONFIG") or os.path.join(here, "configs", f"{name}.yaml")
    if not os.path.exists(path):
        path = os.path.join(here, "configs", "default.yaml")

    with open(path) as f:
        cfg = _merge(DEFAULTS, yaml.safe_load(f) or {})

    cfg["server"] = os.getenv("SERVER_NAME") or cfg.get("server") or name
    cfg["ingest_url"] = os.getenv("INGEST_URL", cfg.get("ingest_url", ""))
    cfg["token"] = os.getenv("AGENT_TOKEN", cfg.get("token", ""))
    cfg["dry_run"] = os.getenv("AGENT_DRY_RUN", "0") == "1" or not cfg["ingest_url"]
    cfg["config_path"] = path
    return cfg
