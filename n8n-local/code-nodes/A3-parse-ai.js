// Node "Parse AI"  ·  Code node  ·  Mode: Run Once for All Items
const v = $('Validate').first().json;
const res = $input.first().json;
const content = res?.choices?.[0]?.message?.content || '';

let ai = null;
try { ai = JSON.parse(content); } catch (e) { ai = null; }

// Fallback: never lose an alert just because the AI answer was broken/empty
if (!ai || typeof ai !== 'object') {
  ai = {
    severity: v.max_level === 'critical' ? 'high' : 'medium',
    title: `Unanalyzed ${v.max_level} events on ${v.server}`,
    root_cause: 'AI response could not be parsed. First event: ' +
      (v.fresh_events[0]?.message || 'n/a'),
    affected_servers: [v.server],
    fix_steps: [],
    confidence: 0,
    needs_human: true,
    parse_failed: true,
  };
}

const SEV = ['info', 'low', 'medium', 'high', 'critical'];
const severity = SEV.includes(String(ai.severity).toLowerCase())
  ? String(ai.severity).toLowerCase() : 'medium';
const confidence = Math.max(0, Math.min(1, Number(ai.confidence) || 0));
const servers = Array.isArray(ai.affected_servers) && ai.affected_servers.length
  ? ai.affected_servers.map(String) : [v.server];
const steps = Array.isArray(ai.fix_steps) ? ai.fix_steps.slice(0, 4).map(String) : [];
const title = String(ai.title || 'Untitled incident').slice(0, 120);
const cause = String(ai.root_cause || '').slice(0, 1500);

// Telegram (HTML parse mode) -- escape &, <, >
const esc = s => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const icon = { critical: '🔴', high: '🟠', medium: '🟡', low: '🔵', info: '⚪' }[severity];
let text = `${icon} <b>${severity.toUpperCase()} — ${esc(title)}</b>\n`
  + `Servers: ${esc(servers.join(', '))}${ai.correlated ? ' (correlated)' : ''}\n\n`
  + `<b>Cause:</b> ${esc(cause)}`;
if (steps.length) text += `\n\n<b>Fix:</b>\n` + steps.map((s, i) => `${i + 1}) ${esc(s)}`).join('\n');
text += `\n\nConfidence: ${confidence.toFixed(2)}${ai.needs_human ? ' · needs human' : ''}`;

return [{
  json: {
    signature: v.signature,
    severity,
    title,
    root_cause: cause,
    affected_servers: servers,
    fix_steps: steps,
    confidence,
    should_alert: ['high', 'critical'].includes(severity),
    telegram_text: text.slice(0, 3900),
    ai_raw: ai,
  },
}];
