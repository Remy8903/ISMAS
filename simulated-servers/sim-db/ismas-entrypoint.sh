#!/bin/bash
# Start agent in background (restart loop), then hand over to MariaDB's entrypoint.
( while true; do python3 -u /opt/agent/agent.py >> /var/log/agent.log 2>&1; sleep 5; done ) &
exec docker-entrypoint.sh "$@"
