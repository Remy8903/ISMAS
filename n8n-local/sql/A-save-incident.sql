-- Node "Save Incident"  |  Query Parameters:  {{ [ JSON.stringify($json) ] }}
INSERT INTO incidents (signature, severity, title, root_cause, affected_servers,
                       fix_steps, confidence, alerted, ai_raw)
SELECT j->>'signature', j->>'severity', j->>'title', j->>'root_cause',
       ARRAY(SELECT jsonb_array_elements_text(COALESCE(j->'affected_servers', '[]'::jsonb))),
       j->'fix_steps', (j->>'confidence')::numeric, (j->>'should_alert')::boolean, j->'ai_raw'
FROM (SELECT $1::jsonb AS j) d
RETURNING id;
