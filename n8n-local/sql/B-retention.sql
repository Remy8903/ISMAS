-- Node "Retention" (Workflow B, daily)  |  no parameters
DELETE FROM payloads WHERE received_at < now() - interval '7 days';
DELETE FROM events   WHERE received_at < now() - interval '7 days';
