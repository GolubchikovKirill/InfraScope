# Deployment Architecture

## Current State

InfraScope already has a microservice-oriented Docker Compose setup:

- `frontend` serves the SPA through Nginx and proxies API/WebSocket traffic to `backend`.
- `backend` is the API gateway and owns authentication, UI-facing API, migrations, and orchestration.
- `worker` runs Celery tasks through Redis.
- `polling-service` performs network polling for printers, media players, switches, computers, and cash registers.
- `discovery-service` performs network discovery scans.
- `network-control-service` performs direct switch/media-player control operations.
- `media-service` serves media manifests and media files to Windows media clients.
- `ml-service` runs prediction/training workflows.
- `postgres`, `redis`, `kafka`, `jaeger`, `prometheus`, and `grafana` are infrastructure services.

Production path for this project is Docker Compose only.

## Is Kafka Needed?

Kafka is useful, but it is not mandatory for the core application.

Keep Kafka when you need:

- durable operational event stream;
- service/event audit trail outside the main database;
- future integrations with external systems;
- consumer lag and event-flow visibility through Kafka UI;
- replayable events for analytics or incident investigation.

Kafka is overkill when:

- the app runs on one small server;
- operational events are only shown in the app logs table;
- no other services consume events;
- low maintenance is more important than event-stream durability.

Recommended production stance for the current project:

- Single-machine Docker deployment: Kafka can be disabled with `KAFKA_ENABLED=false` if you want fewer moving parts.
- Microservice/observability deployment: keep Kafka enabled.

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
INTERNAL_SERVICE_TOKEN=...
MEDIA_CLIENT_TOKEN=...
KAFKA_ENABLED=true
NETWORK_CONTROL_SERVICE_ENABLED=true
POLLING_SERVICE_ENABLED=true
DISCOVERY_SERVICE_ENABLED=true
MEDIA_SERVICE_ENABLED=true
```

3. Start or update without touching database volumes:

```bash
docker compose build backend worker frontend polling-service discovery-service network-control-service ml-service media-service
docker compose up -d --no-deps backend worker frontend polling-service discovery-service network-control-service ml-service media-service
```

4. Apply production override:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

5. Check status:

```bash
docker compose ps
docker compose logs backend --tail=100
docker compose logs polling-service --tail=100
docker compose logs network-control-service --tail=100
```

### Stage 2: Microservice Cleanup

Keep this boundary:

- `backend`: UI API, auth, orchestration, database migrations.
- `polling-service`: all direct status polling.
- `discovery-service`: subnet scanning and discovery state.
- `network-control-service`: switch ports, PoE, Iconbit/direct device commands.
- `media-service`: manifests and file delivery for Windows media clients.
- `ml-service`: model training/predictions.
- `worker`: scheduled/long-running tasks.

Avoid adding new direct LAN operations back into `backend`. The backend should call internal services over HTTP with `INTERNAL_SERVICE_TOKEN`.

### Stage 3: Compose Hardening

1. Keep production override minimal and deterministic:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

2. For updates, do rolling restart of app services without removing stateful volumes:

```bash
docker compose build backend worker frontend polling-service discovery-service network-control-service ml-service media-service
docker compose up -d --no-deps backend worker frontend polling-service discovery-service network-control-service ml-service media-service
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
3. Keep microservices enabled for polling, discovery, network control, media, and forecasting.
4. Keep Kafka only if you actively use event stream/Kafka UI. Otherwise disable it to reduce maintenance.
5. Keep deployment model simple: one production path (`docker compose`) and documented rollback steps.
