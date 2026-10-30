"""Turn raw log lines into events: {"level": ..., "message": ...} or None (dropped).
Only warning / error / critical survive -- normal noise never leaves the server."""
import json, re

LEVEL_RANK = {"info": 0, "warning": 1, "error": 2, "critical": 3}

TAG_LEVELS = [
    (re.compile(r"\[(emerg|alert|crit|critical|fatal)\]", re.I), "critical"),
    (re.compile(r"\[(error|err)\]", re.I), "error"),
    (re.compile(r"\[(warn|warning)\]", re.I), "warning"),
    (re.compile(r"\[(note|notice|info|debug)\]", re.I), None),   # explicit low level -> drop
]
KEYWORD_LEVELS = [
    (re.compile(r"\b(fatal|critical|emerg\w*|panic|crash(ed)?|out of memory|oom[- ]?kill\w*|segfault)\b", re.I), "critical"),
    (re.compile(r"\b(error|failed|failure|exception|denied|refused|unreachable)\b", re.I), "error"),
    (re.compile(r"\b(warn(ing)?|deprecated|timeout|timed out)\b", re.I), "warning"),
]


class GenericParser:
    """Syslog / nginx error / php error / mariadb error logs."""
    def parse(self, line):
        line = line.strip()
        if not line:
            return None
        for rx, lvl in TAG_LEVELS:
            if rx.search(line):
                return {"level": lvl, "message": line} if lvl else None
        for rx, lvl in KEYWORD_LEVELS:
            if rx.search(line):
                return {"level": lvl, "message": line}
        return None


class NginxAccessParser:
    RX = re.compile(r'"(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" (?P<status>\d{3}) \d+ rt=(?P<rt>[\d.]+)')

    def __init__(self, thresholds):
        self.slow = float(thresholds["slow_request_s"])

    def parse(self, line):
        m = self.RX.search(line)
        if not m:
            return None
        status, rt = int(m["status"]), float(m["rt"])
        path = m["path"].split("?")[0]
        if status >= 500:
            return {"level": "error", "message": f"HTTP {status} on {m['method']} {path}"}
        if rt >= self.slow:
            return {"level": "warning", "message": f"Slow request {rt:.1f}s on {m['method']} {path}"}
        return None


class AppJsonParser:
    MAP = {"warning": "warning", "warn": "warning", "error": "error",
           "critical": "critical", "alert": "critical", "emergency": "critical"}

    def parse(self, line):
        try:
            d = json.loads(line)
        except ValueError:
            return GenericParser().parse(line)
        lvl = self.MAP.get(str(d.get("level", "")).lower())
        if not lvl:
            return None
        msg = str(d.get("msg", ""))
        ctx = d.get("ctx") or {}
        if isinstance(ctx, dict) and ctx.get("error"):
            msg += f" | {ctx['error']}"
        if d.get("path"):
            msg += f" (path {str(d['path']).split('?')[0]})"
        return {"level": lvl, "message": msg}


class MysqlSlowParser:
    """Multi-line slow log: '# Query_time: N ...' followed by the query."""
    RX = re.compile(r"#\s*Query_time:\s*([\d.]+)")

    def __init__(self, thresholds):
        self.crit = float(thresholds["slow_query_crit_s"])
        self.pending = None

    def parse(self, line):
        m = self.RX.match(line)
        if m:
            self.pending = float(m.group(1))
            return None
        s = line.strip()
        if self.pending is None or not s or s.startswith("#") or s.upper().startswith(("SET TIMESTAMP", "USE ")):
            return None
        qt, self.pending = self.pending, None
        return {"level": "critical" if qt >= self.crit else "warning",
                "message": f"Slow query {qt:.1f}s: {s[:300]}"}


def make_parser(kind, thresholds):
    if kind == "nginx_access":
        return NginxAccessParser(thresholds)
    if kind == "app_json":
        return AppJsonParser()
    if kind == "mysql_slow":
        return MysqlSlowParser(thresholds)
    return GenericParser()
