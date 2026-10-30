"""System metrics. Cgroup-aware: inside a container, reports the container's
own CPU/RAM limits instead of the whole host/WSL VM."""
import os, time
import psutil

CG = "/sys/fs/cgroup"


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


class Metrics:
    def __init__(self):
        self.cgroup = os.path.exists(f"{CG}/cgroup.controllers") and _read(f"{CG}/memory.current") is not None
        self._prev_cpu = None
        self.cpu_percent()  # prime the delta

    # ---- CPU ----
    def cpu_limit(self):
        v = _read(f"{CG}/cpu.max") if self.cgroup else None
        if v:
            quota, period = v.split()
            if quota != "max":
                return int(quota) / int(period)
        return psutil.cpu_count() or 1

    def cpu_percent(self):
        if not self.cgroup:
            return psutil.cpu_percent(interval=None)
        stat = _read(f"{CG}/cpu.stat") or ""
        usage = next((int(l.split()[1]) for l in stat.splitlines() if l.startswith("usage_usec")), 0)
        now = time.monotonic()
        prev, self._prev_cpu = self._prev_cpu, (usage, now)
        if prev is None:
            return 0.0
        du, dt = usage - prev[0], (now - prev[1]) * 1_000_000
        return max(0.0, min(100.0, du / (dt * self.cpu_limit()) * 100)) if dt > 0 else 0.0

    # ---- Memory ----
    def memory(self):
        if self.cgroup:
            used = int(_read(f"{CG}/memory.current") or 0)
            stat = _read(f"{CG}/memory.stat") or ""
            inactive = next((int(l.split()[1]) for l in stat.splitlines() if l.startswith("inactive_file ")), 0)
            used = max(0, used - inactive)                    # same as `docker stats`
            raw_max = _read(f"{CG}/memory.max")
            limit = int(raw_max) if raw_max and raw_max != "max" else psutil.virtual_memory().total
        else:
            vm = psutil.virtual_memory()
            used, limit = vm.total - vm.available, vm.total
        return used, limit

    def collect(self):
        used, limit = self.memory()
        disk = psutil.disk_usage("/")
        try:
            load1 = round(os.getloadavg()[0], 2)
        except OSError:
            load1 = None
        return {
            "cpu_pct": round(self.cpu_percent(), 1),
            "cpu_limit_cores": round(self.cpu_limit(), 2),
            "mem_used_mb": round(used / 1048576, 1),
            "mem_limit_mb": round(limit / 1048576, 1),
            "mem_pct": round(used / limit * 100, 1) if limit else None,
            "disk_pct": round(disk.percent, 1),
            "disk_free_gb": round(disk.free / 1073741824, 2),
            "load1_host": load1,
            "source": "cgroup" if self.cgroup else "host",
        }


def check_processes(names):
    running = set()
    for p in psutil.process_iter(["name"]):
        try:
            running.add((p.info["name"] or "").lower())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return {n: any(n.lower() in r for r in running) for n in names}
