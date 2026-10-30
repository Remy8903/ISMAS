"""POST payloads to n8n. On failure, buffer to disk and resend later."""
import json, os, urllib.request


class Sender:
    def __init__(self, cfg):
        self.url, self.token, self.dry = cfg["ingest_url"], cfg["token"], cfg["dry_run"]
        self.buf, self.buf_max = cfg["buffer_path"], cfg["buffer_max_lines"]
        os.makedirs(os.path.dirname(self.buf), exist_ok=True)

    def _post(self, payload):
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json", "X-ISMAS-Token": self.token})
        with urllib.request.urlopen(req, timeout=5) as r:
            if r.status >= 300:
                raise RuntimeError(f"HTTP {r.status}")

    def send(self, payload):
        if self.dry:
            print(json.dumps(payload, indent=2), flush=True)
            return True
        try:
            self._post(payload)
        except Exception as e:
            print(f"[agent] send failed ({e}); buffering", flush=True)
            self._buffer(payload)
            return False
        self._flush()
        return True

    def _buffer(self, payload):
        with open(self.buf, "a") as f:
            f.write(json.dumps(payload) + "\n")
        with open(self.buf) as f:
            lines = f.readlines()
        if len(lines) > self.buf_max:                     # keep newest only
            with open(self.buf, "w") as f:
                f.writelines(lines[-self.buf_max:])

    def _flush(self, max_items=50):
        if not os.path.exists(self.buf):
            return
        with open(self.buf) as f:
            lines = f.readlines()
        sent = 0
        for line in lines[:max_items]:
            try:
                p = json.loads(line)
                p["resent"] = True
                self._post(p)
                sent += 1
            except Exception:
                break
        rest = lines[sent:]
        if rest:
            with open(self.buf, "w") as f:
                f.writelines(rest)
        else:
            os.remove(self.buf)
        if sent:
            print(f"[agent] resent {sent} buffered payload(s)", flush=True)
