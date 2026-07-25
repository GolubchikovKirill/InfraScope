# InfraScope Domains

InfraScope is easiest to understand as a set of product domains around monitored infrastructure.
Keep new code close to the domain it belongs to, and let shared infrastructure stay in `app/core`,
`app/observability`, and `app/worker`.

## Core Platform

Owns application startup, configuration, database sessions, security, Redis, rate limiting,
readiness checks, and shared API dependencies.

- Backend: `app/main.py`, `app/core/`, `app/api/deps.py`, `app/api/main.py`
- Frontend shell: `frontend/src/App.tsx`, `frontend/src/auth.tsx`, `frontend/src/components/Layout.tsx`
- Tests: `tests/unit/core/`, `tests/integration/api/test_auth.py`, `frontend/src/auth.test.tsx`

Shared compatibility facades remain at `app/models.py` and `app/schemas.py`. New backend code should import
concrete models and schemas from `app/domains/*` instead of adding more definitions to those facades.

## Identity And Access

Owns user accounts, authentication, JWT issuance, password hashing, and session-oriented UI.

- Domain package: `app/domains/identity/`
- Backend routes: `app/api/routes/auth.py`, `app/api/routes/users.py`
- Models and schemas: `User`, user/auth schemas
- Frontend: `frontend/src/pages/Login.tsx`, `frontend/src/pages/Users.tsx`,
  `frontend/src/components/UserForm.tsx`

## Network Inventory

Owns printers, switches, computers, media players, scanner search, and network discovery.
This is the largest domain today; prefer extracting helpers from route files into services
before adding new route-level logic.

- Domain package: `app/domains/inventory/`
- Backend routes: `app/api/routes/printers.py`, `switches/` (package), `computers.py`,
  `media_players.py`, `scanner.py`
- Services: `app/services/snmp/` (package), `cisco_ssh.py`, `device_poll.py`, `discovery.py`,
  `scanner.py`, `smart_search.py`, `switches/`
- Application services: `app/domains/inventory/printer_polling.py`,
  `app/domains/inventory/media_polling.py`, `app/domains/inventory/switch_polling.py`,
  `app/domains/inventory/reachability.py`
- Frontend: `frontend/src/pages/SwitchesPage.tsx`, `ComputersPage.tsx`,
  `MediaPlayersPage.tsx`, `NetworkSearchPage.tsx`, related cards/forms

## Operations And Automation

Owns cash register availability, background jobs, polling loops, mass operations, task status,
event logs, and worker lifecycle.
Code here should depend on services, not API route modules.

- Domain package: `app/domains/operations/`
- Backend: `app/worker/`, `app/polling_service/`, `app/api/routes/tasks.py`,
  `app/api/routes/logs.py`, `app/api/routes/cash_registers.py`
- Application services: `app/domains/operations/cash_register_polling.py`
- Services: `app/services/event_log.py`, `poll_resilience.py`, `service_flow.py`,
  `internal_services.py`, `kafka_events.py`
- Infra: `services/`, `docker-compose*.yml`, `scripts/`, `tools/scaffold/`

## Integrations

Owns external business systems and generated operational artifacts such as QR codes.

- Domain package: `app/domains/integrations/`
- Backend routes: `app/api/routes/onec_exchange.py`, `qr_generator.py`
- Services: `app/services/onec_exchange.py`, `qr_generator.py`, `iconbit.py`
- Frontend: `frontend/src/pages/OneCPage.tsx`, `QrGeneratorPage.tsx`,
  `frontend/src/components/OneCQrPanel.tsx`

## Forecasting And Insights

Owns feature extraction, toner forecasting, model snapshots, and scheduled scoring.

- Domain package: `app/domains/ml/`
- Backend: `app/ml/`, `app/ml_service/`, `app/api/routes/ml.py`
- Services: `app/services/ml_snapshots.py`
- Frontend: dashboard prediction widgets in `frontend/src/pages/Dashboard.tsx`

## Observability And Delivery

Owns metrics, tracing, dashboards, service descriptors, deployment manifests, and operational runbooks.

- Backend: `app/observability/`, `app/api/routes/observability.py`
- Monitoring: `monitoring/`
- Delivery: `infra/`, `docs/runbooks/`, `docs/asyncapi.yml`

## Refactoring Rules

- Route handlers should validate HTTP concerns and delegate business logic to services.
- Services may depend on models, schemas, core clients, and other services in the same or lower-level domain.
- Workers and standalone services must not import API route modules.
- ORM table models live in `app/domains/*/models.py`; `app/models.py` is only a compatibility export.
- Pydantic schemas live in `app/domains/*/schemas.py`; `app/schemas.py` is only a compatibility export.
- Frontend pages should compose API modules, hooks, and components; keep request details out of JSX.
- Shared helpers should move only when two domains genuinely need them.
