-- Node "Context"  |  Query Parameters:  {{ [ $('Validate').first().json.signature ] }}
SELECT
  (SELECT count(*) FROM incidents
    WHERE signature = $1 AND created_at > now() - interval '15 minutes')::int AS recent_dupes,

  (SELECT COALESCE(json_agg(t), '[]'::json) FROM (
     SELECT server, source, level, message, count,
            to_char(last_seen AT TIME ZONE 'Asia/Kuala_Lumpur', 'HH24:MI:SS') AS at
     FROM events
     WHERE received_at > now() - interval '5 minutes' AND level IN ('error', 'critical')
     ORDER BY received_at DESC LIMIT 40) t) AS recent_events,

  (SELECT COALESCE(json_agg(s), '[]'::json) FROM (
     SELECT name, status,
            EXTRACT(EPOCH FROM now() - last_seen)::int AS seconds_since_last_report
     FROM servers ORDER BY name) s) AS servers;
