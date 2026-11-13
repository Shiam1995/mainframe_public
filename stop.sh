#!/usr/bin/env bash
# Stop the API (if running) and the Neo4j container. Data persists in the
# Docker volume mainframe_neo4j_data, so your graph survives restarts.
set -uo pipefail
echo "▸ stopping API (uvicorn)…"; pkill -f "uvicorn main:app" 2>/dev/null && echo "  stopped" || echo "  not running"
echo "▸ stopping Neo4j container…"; docker stop mainframe-neo4j 2>/dev/null && echo "  stopped" || echo "  not running"
echo "done. (data volume kept — use 'docker rm mainframe-neo4j' to remove the container)"
