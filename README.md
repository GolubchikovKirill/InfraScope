# InfraScope

InfraScope — платформа мониторинга инфраструктуры магазинов: принтеры, медиаплееры (Iconbit/неттопы), сетевые свитчи, сетевой discovery, массовые операции, наблюдаемость и алерты.

Проект ориентирован на production: отказоустойчивый polling, Redis/worker, ограничение параллелизма, мониторинг через Prometheus + Grafana.

## Возможности

- Мониторинг принтеров:
  - лазерные (SNMP, тонер K/C/M/Y, MAC-верификация, DHCP-resilience);
  - этикеточные (IP или USB-режим).
- Мониторинг медиаплееров:
  - Iconbit (порт `8081`, статус, плейлист/файлы, remote и bulk операции);
  - неттопы/Twix (онлайн/офлайн и сетевые данные).
- Централизованное медиа:
  - `media-service` отдает неттопам манифест воспроизведения;
  - медиатека хранит загруженные аудио/видео файлы на сервере;
  - Go client забирает назначение и запускает локальный `mpv`/`vlc`;
  - управление идет через `/api/v1/media-center/*`.
- Мониторинг свитчей:
  - универсально через SNMP (online, hostname, uptime, порты где доступно);
  - Cisco-дополнения через SSH (AP/PoE/reboot, управление портами).
- Discovery по сети:
  - отдельные режимы для принтеров, медиаплееров, свитчей;
  - умная фильтрация типов устройств, чтобы уменьшить ложные совпадения.
- Отказоустойчивость:
  - lock от дублирующих `poll-all`;
  - state machine подтверждения офлайна;
  - circuit breaker;
  - jitter;
  - MAC/IP rediscovery.
- Наблюдаемость:
  - `/metrics` на backend и worker;
  - дашборды Grafana (`overview`, `operations`, `worker`, `ml`);
  - SLO/error-budget и эксплуатационные алерты Prometheus.
- Прогнозирование:
  - retrain и scoring в отдельном `ml-service`;
  - прогноз `days_to_replacement` по картриджам;
  - риск offline (low/medium/high).
- Безопасность:
  - JWT + blacklist в Redis;
  - refresh token rotation + revoke при logout/refresh;
  - Argon2id;
  - rate-limit логина;
  - CORS whitelist;
  - HTTPS через Nginx;
  - без insecure default credentials для 1C QR SQL (требуется явная настройка в `.env`);
  - production guard для `FIRST_SUPERUSER_PASSWORD` и `INTERNAL_SERVICE_TOKEN`.
- Frontend:
  - сортировка online выше offline;
  - page-scoped автообновление только на активных страницах вместо глобального `poll-all` по всему приложению;
  - отдельная вкладка `Поиск в сети` для smart/discovery scan и добавления найденных устройств в нужный раздел.
  - отдельная вкладка `QR-генерация` с под-вкладками: `Штрихкоды кассиров` и `Посадочные`.
  - обмен по штрихкоду поддерживает раздельные каналы `Duty Free` и `Duty Paid` (`/api/v1/1c-exchange/by-barcode`).
- Kafka:
  - event-stream operational логов в топик `infrascope.events`;
  - UI для просмотра топиков и сообщений (`kafka-ui`).

---

## Параметры 1С (Duty Free / Duty Paid)

- Для канала `Duty Free`/`Duty Paid` в `.env` можно хранить:
  - `ONEC_DUTY_*_API_URL` и `ONEC_DUTY_*_API_TOKEN` — HTTP endpoint интеграции 1С (обязателен для фактической выгрузки).
  - `ONEC_DUTY_*_IB_CONNECTION`, `ONEC_DUTY_*_DOMAIN`, `ONEC_DUTY_*_TERMINAL_SERVER` — строка базы 1С/домен/терминальный сервер для эксплуатации и диагностики.
- Пример строки базы 1С:
  - `Srvr="vnk-srv-1c02";Ref="trade_rsm_dfree";`
- Важно: сама строка базы `Srvr/Ref` не заменяет `API_URL`; backend выполняет обмен через HTTP endpoint 1С.

---

## Технологический стек

- Backend: `FastAPI`, `SQLModel`, `Alembic`, `PostgreSQL 17`, `Redis`, `Celery`
- Network: `pysnmp-lextudio`, `paramiko`, `httpx`
- Frontend: `React`, `TypeScript`, `Vite`, `TanStack Query`
- Monitoring: `Prometheus`, `Grafana`, `prometheus-fastapi-instrumentator`
- Tracing: `OpenTelemetry`, `Jaeger`
- Infra: `Docker Compose`, `Nginx` (TLS termination)

---

## Запуск в production

### 1) Подготовка

```bash
git clone https://github.com/GolubchikovKirill/InfraScope.git
cd infrascope
cp .env.example .env
```

По умолчанию проект использует `COMPOSE_PROJECT_NAME=infrascope`, поэтому контейнеры и ресурсы будут иметь префикс `infrascope`.

Заполните минимум:

- `SECRET_KEY`
- `POSTGRES_PASSWORD`
- `FIRST_SUPERUSER_PASSWORD`
- `SCAN_SUBNET` (подсети для discovery/scan)

### 2) Старт

```bash
./scripts/deploy-compose-prod.sh
```

Скрипт перед запуском проверяет production `.env`. Если backend падает сразу после старта, сначала проверьте, что в `.env` нет `changethis`/`CHANGE_ME` и коротких значений в `SECRET_KEY`, `FIRST_SUPERUSER_PASSWORD`, `INTERNAL_SERVICE_TOKEN`. `POSTGRES_PASSWORD` для уже созданного volume меняйте только после смены пароля роли внутри PostgreSQL.

Рекомендованный сетевой профиль для сервера `4 vCPU / 16 GB RAM / 1 Gbps`:

```bash
WORKER_CONCURRENCY=6
SCAN_TCP_CONCURRENCY=512
POLL_JITTER_MAX_MS=120
PRINTER_POLL_MAX_WORKERS=32
MEDIA_POLL_MAX_WORKERS=24
SWITCH_POLL_MAX_CONCURRENCY=16
COMPUTER_POLL_CONCURRENCY=48
CASH_REGISTER_POLL_CONCURRENCY=48
```

### 3) Доступ

- Приложение: `https://infrascope.local` или `https://localhost`
- Swagger/OpenAPI: `https://localhost/docs`
- Prometheus: `http://127.0.0.1:9090` (по умолчанию bind на localhost)
- Grafana: `http://127.0.0.1:3000` (по умолчанию bind на localhost)
  - default: `admin` / `admin`
- Kafka UI: `http://127.0.0.1:8080`
- Jaeger (trace UI): `http://127.0.0.1:16686`

> Для доступа по LAN настройте `HOST_IP`, hosts/DNS и при необходимости `PROMETHEUS_BIND` / `GRAFANA_BIND`.

---

## Dev-режим

```bash
docker compose up db redis -d
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

cd frontend
npm install
npm run dev
```

Локальный frontend: `http://localhost:5173`

Если нужен dev-compose с пробросом портов:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

---

## Архитектура сервисов

- `frontend` — SPA + Nginx + HTTPS
- `backend` — API gateway/orchestration, `/metrics`
- `worker` — Celery worker для тяжёлых фоновых задач
- `ml-service` — отдельный сервис прогнозирования + `/metrics`
- `polling-service` — отдельный runtime polling устройств + `/metrics`
- `discovery-service` — отдельный runtime discovery/scan + `/metrics`
- `network-control-service` — отдельный runtime control операций (Iconbit, switch write ops) + `/metrics`
- `media-service` — отдельный runtime выдачи media manifest и файлов медиатеки для клиентских неттоп-агентов + `/metrics`
- `kafka` — event bus для operational событий
- `kafka-ui` — web-интерфейс Kafka
- `jaeger` — distributed tracing (цепочки вызовов между сервисами)
- `db` — PostgreSQL
- `redis` — cache/locks/broker/backend
- `prometheus` — сбор метрик
- `grafana` — визуализация

Compose healthcheck у Python-сервисов проверяет `/health`: это только признак, что процесс поднялся и отвечает по HTTP. Готовность внешних зависимостей проверяется отдельно через `/ready`, чтобы временная проблема PostgreSQL/Redis/Kafka не блокировала старт всех контейнеров каскадом.

### Plug-and-play service platform

Сервисная платформа переведена на descriptor-подход:

- каждый сервис описывается в `services/<service>/service.yaml`;
- topology сервисов берется из `services/catalog.yaml` (без hardcode);
- есть scaffold-генератор нового сервиса: `tools/scaffold/new_service.py`;
- есть schema validation: `tools/scaffold/validate_service_descriptors.py`;
- observability-артефакты (Prometheus targets/alerts + Grafana dashboard) автогенерируются из descriptor-ов: `tools/scaffold/generate_observability_assets.py`.

Добавление нового сервиса:

```bash
uv run python tools/scaffold/new_service.py --name inventory-service --port 8020
uv run python tools/scaffold/validate_service_descriptors.py
uv run python tools/scaffold/generate_observability_assets.py
```

Production ориентир проекта — `Docker Compose`.
Kubernetes и `kind` исключены из основного эксплуатационного контура.

### Прод-обновление без пересоздания БД

Обновить код и контейнеры (с сохранением volume БД):

```bash
chmod +x scripts/deploy-compose-prod.sh
./scripts/deploy-compose-prod.sh
```

Поднять стек заново с чистыми контейнерами и сетями, но сохранить БД/volume:

```bash
./scripts/deploy-compose-prod.sh --clean
```

Полный сброс с удалением volume и пустой БД требует явного подтверждения. Скрипт сначала попробует сохранить дамп в `backups/`:

```bash
CONFIRM_RESET_VOLUMES=YES ./scripts/deploy-compose-prod.sh --reset-volumes
```

Если нужно пересобрать вообще без Docker cache:

```bash
FORCE_NO_CACHE=1 ./scripts/deploy-compose-prod.sh --clean
```

Проверка:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl -kfsS https://localhost/ready
```

### Быстрый rollback

1. Переключить git на предыдущий стабильный коммит/тег.
2. Перезапустить сервисы без удаления volume:

```bash
./scripts/deploy-compose-prod.sh
```

БД при этом не удаляется, пока вы не делаете `docker compose down -v`.

### Миграция старого volume `sitegka_postgres_data` (legacy)

Если данные остались в старом volume:

```bash
docker volume create infrascope_postgres_data
docker run --rm -v sitegka_postgres_data:/from -v infrascope_postgres_data:/to alpine sh -c "cd /from && cp -a . /to"
```

---

## Ключевые переменные окружения

Полный список в `.env.example`.

- База/безопасность:
  - `ENVIRONMENT`, `SECRET_KEY`
  - `POSTGRES_*`
  - `REDIS_URL`
  - `FIRST_SUPERUSER_*`
  - `INTERNAL_SERVICE_TOKEN`
- Сканирование/сеть:
  - `SCAN_SUBNET`, `SCAN_PORTS`
  - `SCAN_MAX_HOSTS`, `SCAN_TCP_TIMEOUT`, `SCAN_TCP_RETRIES`, `SCAN_TCP_CONCURRENCY`
- Poll resilience:
  - `POLL_JITTER_MAX_MS`
  - `POLL_OFFLINE_CONFIRMATIONS`
  - `POLL_CIRCUIT_FAILURE_THRESHOLD`
  - `POLL_CIRCUIT_OPEN_SECONDS`
  - `POLL_RESILIENCE_STATE_TTL_SECONDS`
- Worker:
  - `WORKER_CONCURRENCY`, `WORKER_POOL`, `WORKER_METRICS_PORT`
- Internal service HTTP policy:
  - `INTERNAL_HTTP_TIMEOUT_SECONDS`
  - `INTERNAL_HTTP_RETRIES`
  - `INTERNAL_HTTP_RETRY_BACKOFF_SECONDS`
- Forecasting:
  - `ML_ENABLED`, `ML_SERVICE_URL`
  - `POLLING_SERVICE_ENABLED`, `POLLING_SERVICE_URL`
  - `DISCOVERY_SERVICE_ENABLED`, `DISCOVERY_SERVICE_URL`
  - `NETWORK_CONTROL_SERVICE_ENABLED`, `NETWORK_CONTROL_SERVICE_URL`
  - `INTERNAL_SERVICE_TOKEN`
  - `KAFKA_ENABLED`, `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_EVENT_TOPIC`
  - `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAMESPACE`
  - `PROMETHEUS_API_URL`, `JAEGER_API_URL`, `JAEGER_UI_URL`, `KAFKA_UI_URL`
  - `ML_MIN_TRAIN_ROWS`, `ML_RETRAIN_HOUR_UTC`, `ML_SCORE_INTERVAL_MINUTES`
- Monitoring:
  - `PROMETHEUS_BIND`, `PROMETHEUS_PORT`, `PROMETHEUS_RETENTION`
  - `GRAFANA_BIND`, `GRAFANA_PORT`, `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`
  - `KAFKA_UI_BIND`, `KAFKA_UI_PORT`
  - `JAEGER_BIND`, `JAEGER_PORT`

---

## API

Базовый префикс: `/api/v1`

- Auth/User: `/auth/*`, `/users/*`
- Printers: `/printers/*`, `/scanner/*` (printer discovery)
- Media Players: `/media-players/*`, `/media-players/discover/*`
- Media Center: `/media-center/*`, манифест клиента: `media-service /clients/{player_id}/manifest`
- Switches: `/switches/*`, `/switches/discover/*`
- Tasks/Worker: `/tasks/*`
- Forecasting API: `/ml/*`
- Observability API: `/observability/service-map`, `/observability/service-map/timeseries`
- System: `/health`, `/metrics`
- Readiness: `/ready`

Актуальная спецификация API: `https://localhost/docs`

---

## Security Checklist Перед Go-Live

- Установить уникальные значения для:
  - `SECRET_KEY`
  - `POSTGRES_PASSWORD`
  - `FIRST_SUPERUSER_PASSWORD` (`production` не стартует с пустым/слабым значением)
  - `INTERNAL_SERVICE_TOKEN` (обязателен при включенных внутренних сервисах в `production`)
  - `GRAFANA_ADMIN_PASSWORD`
  - `QR_SQL_LOGIN`, `QR_SQL_PASSWORD` (если используется QR генерация через SQL)
  - `QR_SQL_DUTY_FREE_SERVER`, `QR_SQL_DUTY_FREE_DATABASE`
  - `QR_SQL_DUTY_PAID_SERVER`, `QR_SQL_DUTY_PAID_DATABASE`
  - `QR_SQL_DATABASE` как fallback, если имя базы одинаковое для обоих каналов
  - `QR_SQL_TIMEOUT_SECONDS` (таймаут SQL-запроса для QR-генерации)
- Проверить, что monitoring/UI-порты не открыты наружу без VPN/reverse proxy:
  - `PROMETHEUS_BIND`, `GRAFANA_BIND`, `KAFKA_UI_BIND`, `JAEGER_BIND`
- Проверить whitelist CORS (`BACKEND_CORS_ORIGINS`) и удалить лишние origin.
- Ротация и хранение секретов: не хранить реальные пароли в Git, использовать `.env`/secret-store.
- Проверить, что frontend websocket `/api/v1/realtime/ws` проходит через Nginx и не дает `404` в production.

---

## Наблюдаемость

- Grafana dashboards:
  - `infrascope-overview`
  - `infrascope-operations`
  - `infrascope-worker`
  - `infrascope-services-catalog` (generated from `services/*/service.yaml`)
- Алерты Prometheus покрывают:
  - backend/worker down;
  - API 5xx и latency;
  - error-budget burn (fast/slow);
  - high offline ratio / device availability SLO;
  - всплески SNMP/SSH/port-operation ошибок;
  - всплески `circuit_opened`.

---

## Эксплуатационные заметки

- Глобальное автообновление фронта: фиксированные 15 минут для всех устройств.
- Массовые polling-ручки защищены от спама повторными кликами.
- `docker-compose.prod.yml` оставлен минимальным и безопасным, без сложных network override.
- Для macOS/Windows (Docker Desktop VM) больше опирайтесь на SNMP/HTTP fingerprint, чем на ARP.
- Для предсказуемого апдейта на сервере используйте `./scripts/deploy-compose-prod.sh`.

### Kafka: как смотреть и пользоваться

После `./scripts/deploy-compose-prod.sh` Kafka уже поднята автоматически, отдельной ручной настройки не требуется.

1. Откройте UI: `http://127.0.0.1:8080`.
2. Выберите кластер `infrascope`.
3. Откройте топик `infrascope.events` — там operational события (offline/online, IP changes, critical errors и т.д.).

Важно: Kafka UI показывает топики/сообщения/consumer lag, но не полноценную карту связей сервисов.
Для визуализации цепочек "кто кого вызвал" используйте Jaeger.

CLI-проверка из контейнера Kafka:

```bash
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 --topic infrascope.events --from-beginning
```

Создать тестовое сообщение:

```bash
docker compose exec kafka /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server kafka:9092 --topic infrascope.events
```

### Tracing: карта связей между сервисами

После деплоя откройте `http://127.0.0.1:16686`:

1. Выберите сервис (`backend`, `polling-service`, `discovery-service`, `network-control-service`, `ml-service`).
2. Нажмите **Find Traces** и посмотрите end-to-end цепочку запроса.
3. Для переходов между API и Kafka используйте поле `trace_id` в сообщениях `infrascope.events`.

`trace_id` теперь публикуется в Kafka payload и может быть использован для склейки событий и трейсов.

Спецификация event-контракта: `docs/asyncapi.yml`.

### NetSupport Manager

В текущем UI для касс и медиаплееров используется безопасный режим:
кнопка копирует `hostname` для ручного подключения в NetSupport Manager.
Это исключает нестабильность URI-handler на рабочих станциях и упрощает поддержку.

---

## Обновление

```bash
git pull
docker compose up -d --build
```

### Обновление на другой машине без удаления БД

Важно: PostgreSQL хранится в Docker volume `infrascope_postgres_data`. Не выполняйте `docker compose down -v`, `docker volume rm ...` и `docker system prune --volumes`, если нужно сохранить базу.

```bash
cd /path/to/infrascope
git status
git pull
docker compose build backend worker frontend polling-service discovery-service network-control-service ml-service media-service
docker compose up -d --no-deps backend worker frontend polling-service discovery-service network-control-service ml-service media-service
docker compose ps
```

Если менялись зависимости или нужно проще пересобрать всё приложение, но не трогать БД:

```bash
git pull
docker compose up -d --build
```

Эта команда не удаляет volume с PostgreSQL. База сохранится, пока не используется флаг `-v`.

После обновления:

```bash
docker compose logs backend --tail=100
docker compose exec backend alembic upgrade head
```

Для медиатеки используется отдельный Docker volume `media_library`. Его тоже не удаляйте, если нужно сохранить загруженные видео и музыку.

Для доступа по обычному HTTP в локальной сети оставьте в `.env`:

```env
AUTH_COOKIE_SECURE=false
ACCESS_TOKEN_EXPIRE_MINUTES=10080
REFRESH_TOKEN_EXPIRE_MINUTES=43200
```

`AUTH_COOKIE_SECURE=true` включайте только если сайт открыт по HTTPS, иначе браузер не сохранит refresh-cookie и сессия будет сбрасываться после истечения access-token.

Production smoke/contract check:

```bash
./scripts/smoke-contract.sh
```

## Логи

```bash
docker compose logs backend --tail=200 -f
docker compose logs worker --tail=200 -f
docker compose logs frontend --tail=100 -f
docker compose logs prometheus --tail=100
docker compose logs grafana --tail=100
```

---

## Лицензия

Внутренний проект.
