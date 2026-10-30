"""Masking of sensitive data + grouping of repeated events."""
import hashlib, re, socket
from datetime import datetime

_SALT = socket.gethostname()

RX_SECRET = re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|authorization)(\"?'?\s*[:=]\s*\"?'?)([^\s\"'&,;]+)")
RX_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
RX_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
RX_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
RX_LONGHEX = re.compile(r"\b[a-fA-F0-9]{32,}\b")


def _h(v):
    return hashlib.sha256((_SALT + v).encode()).hexdigest()[:6]


def mask(text, opts):
    text = RX_SECRET.sub(lambda m: f"{m[1]}{m[2]}***", text)
    text = RX_BEARER.sub("Bearer ***", text)
    text = RX_LONGHEX.sub("<hex>", text)
    text = RX_EMAIL.sub(lambda m: f"<email:{_h(m[0])}>" if opts.get("hash_emails") else "<email>", text)
    # hashed IPs keep "same attacker" visible to the AI without exposing the address
    text = RX_IPV4.sub(lambda m: f"<ip:{_h(m[0])}>" if opts.get("hash_ips") else "<ip>", text)
    return text


_RX_NUM = re.compile(r"\d+(\.\d+)?")
_RX_TOKEN = re.compile(r"<(ip|email):\w+>")


def signature(source, level, message):
    norm = _RX_TOKEN.sub(r"<\1>", message.lower())
    norm = _RX_NUM.sub("N", norm)
    norm = re.sub(r"\s+", " ", norm).strip()[:200]
    return f"{source}|{level}|{norm}"


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Aggregator:
    def __init__(self):
        self.groups = {}

    def add(self, source, level, message, fast_sent=False):
        sig = signature(source, level, message)
        g = self.groups.get(sig)
        ts = now_iso()
        if g:
            g["count"] += 1
            g["last_seen"] = ts
            g["already_alerted"] = g["already_alerted"] or fast_sent
        else:
            self.groups[sig] = {
                "source": source, "level": level, "message": message[:500],
                "count": 1, "first_seen": ts, "last_seen": ts,
                "already_alerted": fast_sent,
            }
        return sig

    def drain(self, limit):
        from .parsers import LEVEL_RANK
        events = sorted(self.groups.values(),
                        key=lambda e: (LEVEL_RANK[e["level"]], e["count"]), reverse=True)
        self.groups = {}
        return events[:limit], max(0, len(events) - limit)
