#!/usr/bin/env bash
# Smoke test for the Docker stack: run after `docker compose up -d --build --wait`.
#
# Checks, through the gateway on 127.0.0.1:8080: the gateway and API are healthy, PostgreSQL,
# Redis, and Kafka are in use, the web UI loads, and 1 chat turn goes through Kafka to a worker
# and back into the saved transcript. Finally, no container has restarted.
#
# With placeholder API keys (as in CI) the turn fails at the search step and records an error
# in the chat, which still proves the queue path. With real keys it makes 1 small billed
# lookup (1 search and 1 model call) and stops at the website question.
set -euo pipefail

GATEWAY="${GATEWAY:-http://127.0.0.1:8080}"
json() { python3 -c "import sys, json; print(json.load(sys.stdin)$1)"; }

echo "1. Gateway and API health"
curl -fsS "$GATEWAY/gateway/health"; echo
health="$(curl -fsS "$GATEWAY/api/health")"; echo "$health"
for backend in PostgresStore PostgresSessionStore RedisShortTerm KafkaQueue; do
  grep -q "$backend" <<<"$health" || { echo "missing backend: $backend"; exit 1; }
done

echo "2. Web UI"
curl -fsS -o /dev/null "$GATEWAY/"

echo "3. A chat turn through Kafka and a worker"
chat="$(curl -fsS -X POST "$GATEWAY/api/chats" | json "['chat_id']")"
job="$(curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"message": "Research for me Linear"}' "$GATEWAY/api/chats/$chat/messages" | json "['job_id']")"
status=queued
for _ in $(seq 1 60); do
  status="$(curl -fsS "$GATEWAY/api/chat-jobs/$job" | json "['status']")"
  [[ "$status" == done || "$status" == failed ]] && break
  sleep 2
done
[[ "$status" == done || "$status" == failed ]] || { echo "the turn never finished (status: $status)"; exit 1; }
replies="$(curl -fsS "$GATEWAY/api/chats/$chat" | json "['messages']" | grep -o "'role': 'assistant'" | wc -l)"
echo "turn $status, $replies assistant messages saved"
[[ "$replies" -ge 1 ]] || { echo "no reply was saved in the chat"; exit 1; }

echo "4. No container restarted"
restarts="$(docker inspect --format '{{.RestartCount}}' $(docker compose ps -q) | sort -u)"
[[ "$restarts" == 0 ]] || { echo "restart counts: $restarts"; docker compose ps; exit 1; }

echo "Docker stack OK"
