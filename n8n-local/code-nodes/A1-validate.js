// Node "Validate"  ·  Code node  ·  Mode: Run Once for All Items  ·  Language: JavaScript
const req = $input.first().json;
const p = req.body || {};
const token = (req.headers && req.headers['x-ismas-token']) || '';
const valid = token !== '' && token === $env.ISMAS_AGENT_TOKEN
              && p.schema === 'ismas.v1' && !!p.server;

const RANK = { info: 0, warning: 1, error: 2, critical: 3 };
const events = Array.isArray(p.events) ? p.events.slice(0, 50) : [];
const maxLevel = events.reduce(
  (m, e) => ((RANK[e.level] ?? 0) > (RANK[m] ?? 0) ? e.level : m), 'info');

// New error/critical events the AI hasn't analyzed yet
const fresh = events.filter(e =>
  (RANK[e.level] ?? 0) >= 2 && (p.type === 'critical' || !e.already_alerted));

// Fingerprint of "this problem" for dedup (numbers / hashes stripped)
const norm = s => String(s).toLowerCase()
  .replace(/<(ip|email):\w+>/g, '<$1>')
  .replace(/\d+(\.\d+)?/g, 'N')
  .slice(0, 160);
const sigSrc = [...new Set(fresh.map(e => `${p.server}|${e.source}|${e.level}|${norm(e.message)}`))]
  .sort().join('||');
let h = 5381;
for (const c of sigSrc) h = ((h << 5) + h + c.charCodeAt(0)) >>> 0;

return [{
  json: {
    valid,
    server: p.server || null,
    type: p.type || null,
    sent_at: p.sent_at || null,
    max_level: maxLevel,
    needs_ai: valid && fresh.length > 0,
    signature: sigSrc ? 'sig_' + h.toString(16) : null,
    fresh_events: fresh,
    payload: p,
  },
}];
