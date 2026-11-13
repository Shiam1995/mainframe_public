#!/usr/bin/env bash
# Paper Metabolism — one-command local start.
# Brings up Neo4j (Docker) + the FastAPI app. Fully local; no cloud calls.
set -euo pipefail
cd "$(dirname "$0")"

NEO4J_NAME="mainframe-neo4j"
NEO4J_PASS="${NEO4J_PASSWORD:-mainframe}"

echo "▸ Neo4j…"
if ! docker ps --format '{{.Names}}' | grep -q "^${NEO4J_NAME}$"; then
  if docker ps -a --format '{{.Names}}' | grep -q "^${NEO4J_NAME}$"; then
    docker start "${NEO4J_NAME}" >/dev/null
    echo "  started existing container"
  else
    docker run -d --name "${NEO4J_NAME}" \
      -p 7474:7474 -p 7687:7687 \
      -e NEO4J_AUTH="neo4j/${NEO4J_PASS}" \
      -e NEO4J_server_memory_pagecache_size=512M \
      -v mainframe_neo4j_data:/data \
      neo4j:5-community >/dev/null
    echo "  created container (first boot ~20s)"
  fi
else
  echo "  already running"
fi

echo "▸ Python env…"
cd backend
if [ ! -d .venv ]; then python3 -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

echo "▸ Waiting for Neo4j bolt…"
for _ in $(seq 1 40); do
  if python -c "from neo4j import GraphDatabase as G; d=G.driver('bolt://localhost:7687',auth=('neo4j','${NEO4J_PASS}')); d.verify_connectivity(); d.close()" 2>/dev/null; then
    echo "  ready"; break
  fi
  sleep 3
done

echo "▸ Ollama (optional, local LLM)…"
if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "  up — extraction will use Ollama"
else
  echo "  not detected — extraction falls back to the built-in heuristic (still works)"
fi

echo "▸ API → http://localhost:8000"
exec uvicorn main:app --host 0.0.0.0 --port 8000
