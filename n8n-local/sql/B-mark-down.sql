-- Node "Mark Down" (Workflow B)  |  no parameters
WITH down AS (
  UPDATE servers SET status = 'down'
  WHERE status = 'up' AND last_seen < now() - interval '90 seconds'
  RETURNING name, last_seen
),
ins AS (
  INSERT INTO incidents (signature, severity, title, root_cause, affected_servers, alerted)
  SELECT 'down_' || name, 'critical', name || ' stopped reporting',
         'No data received from agent since ' || to_char(last_seen AT TIME ZONE 'Asia/Kuala_Lumpur', 'HH24:MI:SS'),
         ARRAY[name], true
  FROM down
)
SELECT name,
       to_char(last_seen AT TIME ZONE 'Asia/Kuala_Lumpur', 'HH24:MI:SS') AS last_seen_at,
       EXTRACT(EPOCH FROM now() - last_seen)::int AS silent_s
FROM down;
