#!/usr/bin/env bash
# Start the development PostgreSQL (pgvector-capable) and Redis containers used by the server and its database tests.
#   tools/dev-services.sh            start (or reuse) both containers
#   tools/dev-services.sh stop       stop and remove them
# Then:  export AIJADE_TEST_DATABASE_URL=postgres://aijade:aijade@127.0.0.1:55432/aijade
#        export REDIS_URL=127.0.0.1:56379
set -euo pipefail
if [[ "${1:-}" == "stop" ]]; then
  docker rm -f aijade-next-db aijade-next-redis >/dev/null 2>&1 || true
  exit 0
fi
docker start aijade-next-db >/dev/null 2>&1 || docker run -d --name aijade-next-db -e POSTGRES_PASSWORD=aijade -e POSTGRES_USER=aijade \
  -e POSTGRES_DB=aijade -p 127.0.0.1:55432:5432 ghcr.io/tensorchord/vchord-postgres:pg18-v1.0.0 >/dev/null
docker start aijade-next-redis >/dev/null 2>&1 || docker run -d --name aijade-next-redis -p 127.0.0.1:56379:6379 redis:7-alpine >/dev/null
for _ in $(seq 1 30); do
  docker exec aijade-next-db pg_isready -U aijade >/dev/null 2>&1 && break
  sleep 1
done
echo "postgres: postgres://aijade:aijade@127.0.0.1:55432/aijade   redis: 127.0.0.1:56379"
