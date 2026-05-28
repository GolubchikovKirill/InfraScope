# Production Readiness Checklist

Актуально для релиза после `refactor and harden QR/boarding production slice`.

## 1) Build and Runtime Health

- [x] `docker compose up -d --build` проходит без ошибок.
- [x] Все ключевые сервисы в `docker compose ps` имеют `healthy`.
- [x] Frontend proxy readiness отвечает `200` на `https://localhost/ready`.
- [x] Backend readiness отвечает корректный JSON со статусом `ready`.

## 2) Backend Quality and API

- [x] Unit + integration проверки для QR/boarding и 1C exchange проходят.
- [x] Boarding pass генерация отдает реальный scannable 2D-код в PNG.
- [x] API routes для QR/boarding используют thin-orchestration слой.
- [x] Ошибки сервисов нормализованы в общий helper (`_service_errors.py`).

## 3) Frontend UX/State Consistency

- [x] Общие примитивы состояний присутствуют: `LoadingState`, `ErrorState`, `EmptyState`.
- [x] Переиспользуемые контейнеры/UI actions присутствуют: `SectionCard`, `FormActions`.
- [x] Панели `OneCQrPanel` и `BoardingPassPanel` используют единый подход к feedback/error.
- [x] Страница `QR-генерация` отражает текущую функциональность (без legacy выгрузки товара).

## 4) CI/CD and Deploy Safety

- [x] CI содержит backend quality baseline (`ruff` + core pytest smoke).
- [x] CI включает route-service contract smoke для `boarding/qr/1c`.
- [x] Frontend typecheck вынесен в отдельный npm script.
- [x] Deploy script поддерживает безопасный режим prebuilt image по умолчанию.
- [x] Локальная пересборка включается только явным `--build-local`.

## 5) Architecture Boundaries

- [x] Для интеграционных сервисов используется единый `service-result` контракт.
- [x] Route layer использует единый translation ошибок (`_service_errors.py`) и не содержит domain-logic.
- [x] Frontend API декомпозирован на `api/http.ts` + bounded-context модули.
- [x] Сохранена обратная совместимость импорта через `frontend/src/client.ts`.
- [x] Добавлен архитектурный guard-test: `worker`/`polling-service` не импортируют `app.api.routes` напрямую.
- [x] Убрана private-coupling зависимость `discovery -> scanner._parse_arp_table` (вынесено в `net_inventory`).

## 6) Documentation and Operational Clarity

- [x] README синхронизирован с текущими вкладками `QR-генерация`.
- [x] Инструкции deploy/readiness согласованы с фактическим endpoint check.
- [x] Чек-лист задокументирован и хранится в репозитории.

## 7) Post-release Manual Smoke (recommended)

- [ ] Ручной smoke: login в UI + генерация `Штрихкоды кассиров`.
- [ ] Ручной smoke: генерация `Посадочные` и сканирование результата.
- [ ] Ручной smoke: `1c-exchange/by-barcode` для `duty_free` и `duty_paid`.
- [x] Автоматизированный post-deploy smoke доступен через `scripts/smoke_post_deploy.py`.

> Пункты этого блока зависят от доступности реальных внешних интеграций и выполняются на окружении, где доступны целевые 1C endpoints/данные.
