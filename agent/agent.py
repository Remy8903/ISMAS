"""ISMAS agent v0.4 -- collect, filter, mask, group, send.

Loop:
  every `tick`s                  -> read new log lines, keep warning+ only
  every `process_check_interval` -> check required processes
  every `batch_interval`s        -> send batch (metrics + grouped events) = heartbeat
  critical events                -> sent immediately (with cooldown)
"""
import os, sys, time, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ismas_agent import __version__, config
from ismas_agent.metrics import Metrics, check_processes
from ismas_agent.parsers import make_parser
from ismas_agent.processor import Aggregator, mask, now_iso, signature
from ismas_agent.sender import Sender
from ismas_agent.tailer import FileTailer


class Agent:
    def __init__(self):
        self.cfg = config.load()
        self.th = self.cfg["thresholds"]
        self.metrics = Metrics()
        self.sender = Sender(self.cfg)
        self.agg = Aggregator()
        self.sources = [
            (s.get("source") or os.path.basename(s["path"]), FileTailer(s["path"]), make_parser(s.get("type", "generic"), self.th))
            for s in self.cfg["logs"]
        ]
        self.proc_state = {}
        self.cooldown = {}
        self.stats = {"lines_read": 0, "lines_kept": 0}
        self.window_start = now_iso()

    # ---------- helpers ----------
    def payload(self, kind, events, truncated=0, metrics=None, processes=None):
        return {
            "schema": "ismas.v1",
            "agent_version": __version__,
            "server": self.cfg["server"],
            "type": kind,                                   # "batch" | "critical"
            "sent_at": now_iso(),
            "window_start": self.window_start if kind == "batch" else None,
            "metrics": metrics,
            "processes": processes,
            "events": events,
            "events_truncated": truncated,
            "stats": dict(self.stats) if kind == "batch" else None,
        }

    def record(self, source, level, message):
        """Add an event; fast-send if critical and not in cooldown."""
        message = mask(message, self.cfg["mask"])
        fast = False
        if level == "critical":
            sig = signature(source, level, message)
            if time.time() - self.cooldown.get(sig, 0) >= self.cfg["critical_cooldown"]:
                self.cooldown[sig] = time.time()
                fast = True
                ev = {"source": source, "level": level, "message": message[:500],
                      "count": 1, "first_seen": now_iso(), "last_seen": now_iso()}
                self.sender.send(self.payload("critical", [ev], metrics=self.metrics.collect()))
        self.agg.add(source, level, message, fast_sent=fast)

    # ---------- steps ----------
    def read_logs(self):
        for source, tailer, parser in self.sources:
            for line in tailer.read_lines():
                self.stats["lines_read"] += 1
                ev = parser.parse(line)
                if ev:
                    self.stats["lines_kept"] += 1
                    self.record(source, ev["level"], ev["message"])

    def check_procs(self):
        procs = check_processes(self.cfg["processes"])
        for name, up in procs.items():
            prev = self.proc_state.get(name)
            if not up and prev is not False:
                self.record("process", "critical", f"Process {name} is not running")
            elif up and prev is False:
                self.agg.add("process", "info", f"Process {name} recovered")
        self.proc_state = procs
        return procs

    def metric_events(self, m):
        for key, label in (("cpu_pct", "CPU"), ("mem_pct", "Memory"), ("disk_pct", "Disk")):
            v = m.get(key)
            if v is None:
                continue
            short = key.split("_")[0]
            if v >= self.th[f"{short}_crit"]:
                self.record("metrics", "critical", f"{label} usage critical at {v}%")
            elif v >= self.th[f"{short}_warn"]:
                self.agg.add("metrics", "warning", f"{label} usage high at {v}%")

    def send_batch(self):
        m = self.metrics.collect()
        self.metric_events(m)
        procs = check_processes(self.cfg["processes"])
        events, truncated = self.agg.drain(self.cfg["max_events_per_batch"])
        self.sender.send(self.payload("batch", events, truncated, metrics=m, processes=procs))
        self.stats = {"lines_read": 0, "lines_kept": 0}
        self.window_start = now_iso()

    # ---------- main loop ----------
    def run(self):
        c = self.cfg
        print(f"[agent] v{__version__} server={c['server']} config={c['config_path']} "
              f"dry_run={c['dry_run']} logs={len(self.sources)} procs={c['processes']}", flush=True)
        last_batch = last_proc = time.monotonic()
        while True:
            try:
                self.read_logs()
                now = time.monotonic()
                if now - last_proc >= c["process_check_interval"]:
                    self.check_procs()
                    last_proc = now
                if now - last_batch >= c["batch_interval"]:
                    self.send_batch()
                    last_batch = now
            except Exception:
                traceback.print_exc()
            time.sleep(c["tick"])


if __name__ == "__main__":
    Agent().run()
