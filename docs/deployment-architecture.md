# Deployment Architecture

## Current State

InfraScope already has a microservice-oriented Docker Compose setup:

- `frontend` serves the SPA through Nginx and proxies API/WebSocket traffic to `backend`.
- `backend` is the API gateway and owns authentication, UI-facing API, migrations, and orchestration.
- `worker` runs Celery tasks through Redis.
- Device polling and discovery scans run in `worker` (Celery); the API triggers manual polls in-process.
- Direct switch and Iconbit control operations run in `backend`, behind a per-switch write lock and cooldown.
- `media-service` serves media manifests and media files to Windows media clients.
- Prediction training/scoring runs as Celery tasks in `worker` (there is no separate ml service).
- `postgres`, `redis`, `prometheus`, and `grafana` are infrastructure services. `jaeger` (tracing) is optional and lives in the `tracing` compose profile: start it with `docker compose --profile tracing up -d` (or `COMPOSE_PROFILES=tracing` in `.env`) and set `OTEL_ENABLED=true`. Nothing depends on it.

Production path for this project is Docker Compose only.

## Media asset downloads (decision, 2026-09)

`media-service` is the only part reachable from store networks. Manifest and heartbeat require `X-Media-Client-Token`; `GET /assets/{uuid}/file` deliberately does not. The asset id is a random UUID that only appears in a manifest a token holder received, the content is store audio/video (nothing sensitive), and the Windows clients fetch files with a plain HTTP call that would need a rewrite to carry a header. Revisit if assets ever hold anything non-public: the fix is a per-manifest signed URL, not a shared token on the file route.

## Kafka

Removed. It only carried a copy of the rows already written to the `event_log` table, and nothing consumed the topic, while the backend refused to start without a healthy broker. Operational events live in `event_log`; if an external consumer ever appears, add a broker (or a webhook) back for that concrete need.

## Recommended Rollout Path

### Stage 1: Production Docker Compose

Use this as the primary production approach.

1. Pull changes:

```bash
git pull
```

2. Review `.env`:

```bash
cp .env.example .env
nano .env
```

Required production values:

```bash
SECRET_KEY=...
FIRST_SUPERUSER_EMAIL=...
FIRST_SUPERUSER_PASSWORD=...
POSTGRES_PASSWORD=...
MEDIA_CLIENT_TOKEN=...
MEDIA_SERVICE_ENABLED=true
```

3. Start or update without touching database volumes:

```bash
docker compose build backend worker frontend media-service
docker compose up -d --no-deps backend worker frontend media-service
```

4. Apply production override:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

5. Check status:

```bash
docker compose ps
docker compose logs backend --tail=100
docker compose logs worker --tail=100
docker compose logs --tail=100
```

### Stage 2: Microservice Cleanup

Keep this boundary:

- `backend`: UI API, auth, database migrations, and the direct device commands a person triggers (switch ports, PoE, Iconbit).
- `media-service`: manifests and file delivery for Windows media clients.
- `worker`: scheduled and long-running tasks (polling, discovery scans, ML, AP auto-reboot).

Long-running or scheduled work belongs in `worker`; keep request handlers to short, operator-triggered device commands.

### Stage 3: Compose Hardening

1. Keep production override minimal and deterministic:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

2. For updates, do rolling restart of app services without removing stateful volumes:

```bash
docker compose build backend worker frontend media-service
docker compose up -d --no-deps backend worker frontend media-service
```

3. Verify health and readiness:

```bash
docker compose ps
curl -kfsS https://localhost/ready
```

4. Rollback safely by checking out previous git tag/commit and rerunning the same update commands.

## Practical Recommendation

For the current app, the best near-term setup is:

1. Keep Docker Compose as the production deployment on the office/server machine.
2. Keep Redis and worker enabled.
3. Keep `media-service` as the only separate runtime; polling, discovery, device control and forecasting live in `backend`/`worker`.
4. Keep deployment model simple: one production path (`docker compose`) and documented rollback steps.
