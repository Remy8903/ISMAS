// Node "Build Prompt"  ·  Code node  ·  Mode: Run Once for All Items
const v = $('Validate').first().json;
const ctx = $input.first().json;
const p = v.payload;

const system = `You are ISMAS, a senior SRE assistant analyzing server monitoring data.
Respond ONLY with a single json object, no markdown, using exactly this shape:
{
  "severity": "info" | "low" | "medium" | "high" | "critical",
  "title": "short headline, max 80 chars",
  "root_cause": "2-3 sentences. Cite the evidence (server, source, message, time).",
  "affected_servers": ["server names"],
  "correlated": true | false,
  "fix_steps": ["up to 4 short imperative steps, include shell commands when useful"],
  "confidence": 0.0 to 1.0,
  "needs_human": true | false
}
Rules:
- Use ONLY the data provided. Never invent log lines, servers or numbers.
- A server whose seconds_since_last_report is above 60 may be down or unreachable.
- When events on several servers are related, the earliest failure is usually the root cause; set "correlated": true.
- If evidence is weak or ambiguous, say so in root_cause and lower confidence.
- Severity guide: critical = service down or data at risk; high = users affected now;
  medium = degraded or failing intermittently; low = minor; info = nothing actionable.
Example output:
{"severity":"high","title":"Web app failing: database refusing connections","root_cause":"sim-web /db returns 'Connection refused' since 10:42 while sim-db has not reported for 75s. The database is likely down.","affected_servers":["sim-db","sim-web"],"correlated":true,"fix_steps":["docker start sim-db","Check /var/log/mysql/error.log on sim-db"],"confidence":0.85,"needs_human":true}`;

const data = {
  reporting_server: v.server,
  payload_type: v.type,                 // "critical" = sent immediately by the agent
  sent_at: v.sent_at,
  metrics: p.metrics,
  processes: p.processes,
  new_events: v.fresh_events,
  recent_errors_all_servers_last_5min: ctx.recent_events,
  server_status: ctx.servers,
};

return [{
  json: {
    body: {
      model: 'deepseek-chat',
      temperature: 0.2,
      max_tokens: 800,
      response_format: { type: 'json_object' },
      messages: [
        { role: 'system', content: system },
        { role: 'user', content: 'Analyze this monitoring data and return the json object.\n' + JSON.stringify(data) },
      ],
    },
  },
}];
