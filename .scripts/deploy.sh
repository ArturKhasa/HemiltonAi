#!/usr/bin/env bash
set -euo pipefail

DEPLOY_DIR="/opt/hemilton"
COMPOSE_FILE="docker-compose.prod.yml"
LOG_TAG="[deploy]"

log() { echo "$LOG_TAG $(date '+%Y-%m-%d %H:%M:%S') $*"; }

cd "$DEPLOY_DIR"

log "Pulling latest code..."
git pull origin main

log "Building new image (app stays live)..."
docker compose -f "$COMPOSE_FILE" build app

log "Swapping container..."
docker compose -f "$COMPOSE_FILE" up -d --no-build --remove-orphans

log "Waiting for app to become healthy..."
for i in $(seq 1 30); do
    STATUS=$(docker compose -f "$COMPOSE_FILE" ps --format json app 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('Health','') or d.get('State',''))" 2>/dev/null || echo "unknown")
    if [[ "$STATUS" == "healthy" || "$STATUS" == "running" ]]; then
        log "App status: $STATUS"
        break
    fi
    if [[ $i -eq 30 ]]; then
        log "ERROR: app did not become healthy in 60s"
        docker compose -f "$COMPOSE_FILE" logs --tail=50 app
        exit 1
    fi
    sleep 2
done

log "Removing dangling images..."
docker image prune -f

log "Deploy complete."
