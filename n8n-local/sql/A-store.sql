-- Node "Store"  |  Query Parameters:  {{ [ JSON.stringify($json) ] }}
WITH d AS (SELECT $1::jsonb AS j),
prev AS (
  SELECT status FROM servers WHERE name = (SELECT j->>'server' FROM d)
),
up AS (
  INSERT INTO servers (name, last_seen, status)
  SELECT j->>'server', now(), 'up' FROM d
  ON CONFLICT (name) DO UPDATE SET last_seen = now(), status = 'up'
  RETURNING name
),
p AS (
  INSERT INTO payloads (server, type, sent_at, max_level, needs_ai, body)
  SELECT j->>'server', j->>'type', (j->>'sent_at')::timestamptz,
         j->>'max_level', (j->>'needs_ai')::boolean, j->'payload'
  FROM d
  RETURNING id
),
e AS (
  INSERT INTO events (server, payload_type, source, level, message, count,
                      first_seen, last_seen, already_alerted)
  SELECT d.j->>'server', d.j->>'type', x->>'source', x->>'level', x->>'message',
         COALESCE((x->>'count')::int, 1),
         (x->>'first_seen')::timestamptz, (x->>'last_seen')::timestamptz,
         COALESCE((x->>'already_alerted')::boolean, false)
  FROM d, jsonb_array_elements(COALESCE(d.j->'payload'->'events', '[]'::jsonb)) x
  RETURNING 1
)
SELECT (SELECT status FROM prev)  AS prev_status,
       (SELECT id FROM p)         AS payload_id,
       (SELECT count(*) FROM e)   AS events_stored,
       (SELECT j->>'server' FROM d) AS server;
