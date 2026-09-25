# InfraScope: план доработок (октябрь 2026)

Исполнитель — агент-разработчик. Документ самодостаточен: у каждой задачи есть
файлы, суть и критерий «готово». Он продолжает
[`platform-audit-2026-09.md`](platform-audit-2026-09.md). Сделанное там
(бэкапы, удаление Kafka, свёртка микросервисов в `worker`, async-опрос
принтеров, декоратор задач Celery, удаление фасадов) здесь не повторяется.

Снимок на 25.09.2026, коммит `c499ee5`. Замеры сделаны локально:
Python 3.13, SQLite-профиль тестов.

| Метрика | Значение |
|---|---|
| Бэкенд | 23,4 тыс. строк в `app/`, 93 `async def` в роутерах |
| Фронтенд | ~20 тыс. строк TS/TSX, `tsc --noEmit` чистый |
| Тесты | 590 за 110 с, **1 падает** (`test_rustdesk_endpoint_scripts.py::test_hidden_profile_…`) |
| `ruff check` (текущие правила E, F, I, UP) | чисто |
| `pyright app` (режим basic) | **167 ошибок** в 40+ файлах |
| `ruff` с расширенными правилами (B, SIM, RET, ARG, PL, TRY, RUF…) | ~700 замечаний, из них реально полезных ~250 |

## 0. Правила работы для исполнителя

1. **Ветки.** `main` — прод, `vnk-dev` — разработка. Работа идёт в `vnk-dev`
   (или в короткоживущих ветках от неё с PR в `vnk-dev`). В `main` попадает
   только то, что прошло CI на `vnk-dev`: через PR `vnk-dev → main`.
2. **Одна задача — один коммит или PR**, у каждого зелёные `ruff`, `pyright` и `pytest tests`.
   Не смешивать рефакторинг и изменение поведения в одном коммите.
3. **Знания из инцидентов не терять.** Комментарии «почему» в коде
   (legacy KEX для Cisco, «упала подсеть — это путь», лизы перезагрузки AP,
   grace-период офлайна, классификация SSH-ошибок) переносятся вместе с кодом
   дословно. Удалять такой комментарий можно только вместе с кодом, который он объясняет.
4. **Живое оборудование.** Всё, что меняет путь опроса или записи на
   свитчи/AP/Iconbit, выкатывается по одному типу устройств и сверяется на
   реальном парке: до и после, на тех же устройствах, как в пункте 3.1 аудита.
   Деплой и рестарт `worker`/`beat` не делать в окна автоперезагрузки AP
   (04:30 и 16:30 UTC). Перед рестартом выполнить проверку из `CLAUDE.md`.
5. **Тесты на сервере и деплой** — строго по `CLAUDE.md`: test-builder,
   затем `./scripts/deploy-compose-prod.sh`.
6. Никаких новых зависимостей без необходимости. Никакого переписывания на Go
   (обоснование — раздел 4 аудита).

---

## Фаза A — стабилизация (1–2 дня, первой)

| # | Задача | Файлы | Готово, когда |
|---|---|---|---|
| A1 | Починить падающий тест. Тест ждёт `function Write-UserOpts` и запись опций в `\AppData\Roaming\RustDesk\config` при `hidden`. В закоммиченном скрипте этого нет. Скорее всего, правка осталась незакоммиченной в рабочем дереве на Windows (см. «ловушку №1» в `CLAUDE.md`). Сначала спросить владельца или сверить с сервером, и только если правки нигде нет — дописать её в скрипт | `rustdesk-ksc/*.ps1`, `tests/unit/domains/test_rustdesk_endpoint_scripts.py` | `pytest tests` полностью зелёный |
| A2 | Добавить в триггеры CI ветки `main` и `vnk-dev` (сделано этим коммитом, `v2/*` остались). Проверить первый прогон в Actions и починить то, что упадёт | `.github/workflows/ci.yml` | Зелёный прогон на `vnk-dev` |
| A3 | `pyrefly` перенести из runtime-зависимостей в `dev`; `uv lock` | `pyproject.toml`, `uv.lock` | Прод-образ без `pyrefly` |
| A4 | Расширить `.dockerignore`: `tests/`, `docs/`, `frontend/` (уже есть), `rustdesk-ksc/`, `windows-media-agent/`, `clients/`, `tools/windows/`, `backups/`, `certs/`, `*.json`-сиды, кроме нужных в рантайме (проверить `scripts/import_*`) | `.dockerignore` | Контекст сборки меньше, образ собирается, `prestart.sh` работает |
| A5 | Бинарник `windows-media-agent/*.exe` (9 МБ) убрать из git и публиковать в GitHub Releases. Историю не переписывать | `windows-media-agent/`, README агента | Файла нет в дереве, в README есть ссылка на релиз |
| A6 | `redis.setex` → `redis.set(..., ex=)` (DeprecationWarning в тестах) | `app/services/cache.py` и прочие места с `setex` | Тесты идут без этого warning |

---

## Фаза B — производительность и эффективность (1–2 недели)

Каждый пункт начинать с замера: `infrascope_event_loop_lag_seconds`, latency
из Prometheus или время цикла из логов. Результат «до/после» записать в коммит.

| # | Проблема | Что сделать | Готово, когда |
|---|---|---|---|
| B1 | **Каждый авторизованный запрос блокирует event loop**: `get_current_user` в `app/api/deps.py` — это `async def` с синхронным `session.get(User, …)`. Под двумя воркерами uvicorn это главный источник лага | Сделать зависимость синхронной (`def`, FastAPI сам уведёт её в threadpool) либо выполнять загрузку пользователя через `run_in_threadpool`. Проверку blacklist в Redis оставить async отдельной зависимостью | Лаг loop под нагрузкой (k6/ab, 20 rps на `/api/v1/printers/`) заметно ниже; тесты auth зелёные |
| B2 | **Карточка Iconbit опрашивает устройство каждые 10 с**: `IconbitControls` (`frontend/src/components/MediaPlayerCard.tsx:56`) на каждой онлайн-карточке, запрос идёт напрямую на плеер по HTTP. Одна открытая вкладка — это ~3 запроса в секунду в магазины | Бэкенд: кэш статуса в Redis на 15–20 с по `player_id` (`app/api/routes/media_players.py:iconbit_status`). Фронт: интервал 30 с, `refetchIntervalInBackground: false`, опрашивать только развёрнутую или видимую карточку (IntersectionObserver) | Число запросов к плеерам с открытой страницы падает в 5+ раз, UI отзывчив |
| B3 | Инвалидация кэша через `SCAN namespace:*` на каждую запись (`app/services/cache.py:invalidate_entity_cache`) | Версионированный namespace: ключ `ns:{namespace}:v` (INCR при инвалидации), версия входит в ключ кэша; старые ключи умирают по TTL. Никакого SCAN | `scan_iter` не используется в горячем пути; тесты кэша зелёные |
| B4 | Синхронная работа с БД в `async`-роутерах (87 штук, аудит 3.2): `_get_*_or_404(session, …)` и подобные вызываются прямо в `async def` | Правило: роутер `async def` только если внутри нет sync-БД. Иначе `def` + async-операции (кэш, Redis) через синхронный клиент, либо `run_in_threadpool` для блока БД. Переходить на `AsyncSession` **не надо**: двойной стек дороже пользы. Порядок — по метрике лага, начиная с самых частых ручек (списки устройств, `/logs`, `/remote-access/*`) | Тест-страж (AST): в `async def` роутере нет вызовов `session.exec/get/commit` вне `run_in_threadpool`. Лаг p99 < 50 мс |
| B5 | Нет retention у `eventlog`: пишется на каждый онлайн/офлайн, не чистится | Beat-задача в `ml_daily_cycle`/отдельно: удалять батчами старше `EVENT_LOG_RETENTION_DAYS` (по умолчанию 180) по индексу `created_at` | Настройка в `config.py` и `.env.example`, тест, объём таблицы стабилен |
| B6 | Переизбыточные индексы: у `CashRegister` почти каждое поле `index=True` (~20 индексов на таблицу в 80 строк); каждый опрос пишет `is_online`/`last_polled_at` и обновляет их все | Alembic-миграция: оставить индексы, по которым реально фильтруют/сортируют (сверить с `pg_stat_user_indexes.idx_scan` на проде, только SELECT). Аналогично пройтись по `inventory/models.py` | Миграция обратима, `idx_scan = 0` индексов нет |
| B7 | Опрос свитчей: `asyncio.run` в потоке и новый `SnmpEngine` на каждый вызов (`app/services/switches/snmp_provider.py:54,82,306…`, `device_poll.py:671`, `snmp/mac.py:148`; `SnmpEngine()` создаётся в 9 местах) | Повторить подход из принтеров (аудит 3.1) для **SNMP-части** свитчей и `device_poll`: один `SnmpEngine` на цикл через фабрику в `app/services/snmp/engine.py` (контекст-менеджер с гарантированным `close`). SSH (paramiko) не трогать до решения по scrapli | `SnmpEngine()` вызывается только в фабрике; время цикла свитчей не хуже (~33 с); сверка на парке без расхождений |
| B8 | `worker` в compose ждёт `backend: service_healthy` — лишняя связка: сбой бэкенда останавливает опрос | Убрать зависимость (миграции делает `prestart.sh` бэкенда; для worker достаточно проверки схемы/ретрая при старте) или вынести миграции в одноразовый сервис `migrate` с `service_completed_successfully` | Worker стартует независимо от HTTP-бэкенда; миграции выполняются один раз |
| B9 | Пул БД: `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` одинаковы для backend (×2 воркера uvicorn), worker (6 потоков), beat, media-service | Рассчитать и задать per-service через `environment` в compose; beat — минимальный пул | Сумма соединений < `max_connections` с запасом, задокументировано |
| B10 | Тест `test_create_and_poll_switch` идёт 15 с (реальные сетевые таймауты) | Замокать провайдер/сокет, как это сделано в пункте 1.5 аудита | Весь набор < 90 с |
| B11 | Фронт: частые `refetchInterval` на страницах при наличии WebSocket-инвалидации (`LogsPage` 15 с, `MediaPlayersPage` 15 с, `RemoteAccessPage` 20–30 с, `ScreensPage` 20 с) | Опираться на realtime-события `invalidate` и увеличить интервалы до 60 с как страховку; `refetchOnWindowFocus` оставить | Меньше запросов с простаивающей вкладки, данные по-прежнему свежие |

---

## Фаза C — чистота кода (аналог инспекций PyCharm) (1–2 недели)

Цель: в PyCharm нет предупреждений. Сам PyCharm в CI не запустить, поэтому его
основные инспекции закрываются инструментами в CI, а финальная проверка —
headless-инспекцией PyCharm на машине разработчика.

| PyCharm инспекция | Инструмент в CI |
|---|---|
| Unresolved reference, Incorrect type, Parameter unfilled, Optional member access | `pyright` (standard) |
| PEP 8, unused import/variable, неиспользуемые аргументы, shadowing | `ruff` с расширенными правилами |
| TypeScript: типы и неиспользуемое | `tsc --noEmit` с `noUnusedLocals`, `noUnusedParameters` |

| # | Задача | Готово, когда |
|---|---|---|
| C1 | **Pyright в CI.** Сейчас 167 ошибок, топ файлов: `app/ml/pipeline.py` (18), `domains/inventory/printer_polling.py` (14), `services/cisco_ssh.py` (11), `api/routes/printers.py` (9), `services/onec_exchange.py` (8), роутеры `ml`, `switches/auto_reboot`, `media_polling`, `cartridge_stock`. Типы ошибок: `reportArgumentType` 62, `reportAttributeAccessIssue` 59 (типично: SQLModel-колонки в `select().where(Model.field == …)`, лечится `col(Model.field)` из `sqlmodel`), `reportReturnType` 18, `reportOptionalMemberAccess` 11. Чинить типами, а не `# type: ignore`. `ignore` допустим только для багов стабов сторонних библиотек (pysnmp, paramiko), с комментарием | `uv run pyright app` = 0 ошибок; шаг в CI; конфиг `[tool.pyright]` с `typeCheckingMode = "standard"` |
| C2 | **Расширить ruff**: добавить `B`, `SIM`, `RET`, `C4`, `PIE`, `ARG`, `PERF`, `RUF`, `PLE`, `PLW`, `N`, `TRY` (с исключениями ниже). Главное: `ARG001` (46 шт.) — почти всё `current_user: CurrentUser`, который нужен лишь для проверки доступа. Перенести в `dependencies=[Depends(get_current_user)]` на уровне роутера/APIRouter. `B904` (12) — `raise … from exc`. `RUF100` (44) — лишние `noqa`. `PLW0603` (5) — `global` заменить объектом/`lru_cache`. `PLC0415` (23) — импорт внутри функции разрешён только для разрыва циклов, с комментарием | `ruff check app tests scripts` чисто с новым набором |
| C3 | Осознанно **не** включать шумные правила: `TRY003` (178, сообщения в исключениях — норма для API), `PLR2004` (magic values в протокольном коде SNMP/HTTP), `RUF001/002` (кириллица в строках — продукт на русском), `FBT`, `PLR0913` (в разумных пределах). Зафиксировать список в `pyproject.toml` с комментарием «почему» | Выключенные правила перечислены с причиной |
| C4 | Фронт: `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch` в `tsconfig.json`; ESLint (`typescript-eslint` + `react-hooks`) — правило `exhaustive-deps` находит реальные баги с устаревшими замыканиями | `npm run typecheck` и `npm run lint` чистые, шаг в CI |
| C5 | Подготовить профиль инспекций PyCharm в репозитории: `.idea/inspectionProfiles/Project_Default.xml` (только профиль, остальное из `.idea` в `.gitignore`) с интерпретатором `.venv` и Pyright/ruff-плагинами. Финальная приёмка — владелец запускает `Code → Inspect Code` (или `inspect.bat` headless) на Windows-машине; оставшиеся замечания разбираются отдельным коммитом | Инспекция PyCharm по `app/` без warnings; отчёт приложен к PR |
| C6 | Pre-commit: `scripts/install-git-hooks.sh` должен гонять `ruff check`, `ruff format --check`, `pyright` на изменённых файлах | Хук ставится одной командой и описан в README |

---

## Фаза D — архитектура и SOLID (3–5 недель, можно параллельно с C после C1)

Принципы, по которым принимаются решения в этой фазе:

- **Слои**: `api` (HTTP, схемы ответов, коды) → `domains/*` (правила предметки,
  сервисы) → адаптеры (`snmp`, `ssh`, `http`-клиенты устройств, RustDesk, 1С).
  Домен не знает про FastAPI; адаптер не знает про БД.
- **SRP**: модуль > ~400 строк или класс с несколькими причинами для изменения
  разбивается.
- **OCP/LSP/DIP**: новый тип устройства или вендор добавляется новой
  реализацией протокола (`typing.Protocol`), а не новой веткой `if vendor == …`.
- Лаконичность важнее «энтерпрайзности»: без репозиториев-обёрток над SQLModel
  ради самой обёртки, без DI-контейнеров. Зависимости передаются через
  конструктор или FastAPI `Depends`.

| # | Задача | Файлы | Готово, когда |
|---|---|---|---|
| D1 | **Домен не бросает HTTP-ошибки.** `rustdesk_client.py` импортирует `fastapi.HTTPException`; `services/polling_orchestrator.py` импортирует `app.api.deps.SessionDep`; `services/cache.py` импортирует `app.api.websockets`. Ввести `app/domains/shared/errors.py` (`NotFound`, `Conflict`, `IntegrationUnavailable`, `ValidationFailed`…), маппинг в HTTP — один exception handler в `app/main.py` (есть заготовка `api/routes/_service_errors.py`). Broadcast в websocket — через порт-callback (события), а не импорт из api | `domains/remote_access/rustdesk_client.py`, `services/polling_orchestrator.py`, `services/cache.py`, `main.py` | Тест границ слоёв (`tests/unit/architecture`) запрещает `fastapi` и `app.api` в `app/domains` и `app/services` |
| D2 | **Разбить `domains/remote_access/service.py`** (1338 строк, 48 функций): `devices.py` (CRUD и статусы управляемых машин), `console_sync.py` (сверка с консолью RustDesk), `accounts.py` (учётки консоли), `unlisted.py` (машины вне списка). Публичный API — через `__init__.py`, без изменения поведения | `app/domains/remote_access/` | Ни один файл > 450 строк; тесты без изменений логики зелёные |
| D3 | **Разбить `services/cisco_ssh.py`** (1182 строки): `ssh/compat.py` (legacy KEX, фильтр логов), `ssh/session.py` (`CiscoSSH`, классификация ошибок), `cisco/parsers.py` (чистые функции разбора `show …` — легко тестировать), `cisco/operations.py` (reboot/PoE-cycle/restore). Парсеры покрыть табличными тестами на реальных выводах | `app/services/cisco_ssh.py` → `app/adapters/cisco/` | Файлы < 400 строк; парсеры тестируются без paramiko |
| D4 | **Возможности провайдера вместо проверок вендора.** База уже есть (`services/switches/base.py`, `resolver.py`), но роутеры и домен проверяют `switch.vendor != "cisco"` (`api/routes/switches/access_points.py:48,101,171,203,304`, `domains/inventory/ap_auto_reboot.py:65`). Добавить в протокол провайдера декларацию возможностей (`capabilities: frozenset[Capability]` — `ACCESS_POINTS`, `POE_CYCLE`, `PORT_WRITE`…) и единую проверку-зависимость `require_capability(...)` → 409 с понятным текстом | `app/services/switches/*`, `api/routes/switches/*`, `domains/inventory/ap_auto_reboot.py` | `grep 'vendor [!=]=' app/api app/domains` пуст; новый вендор с AP = новый провайдер без правок роутеров |
| D5 | **Довести перенос `app/services` → доменов/адаптеров** (аудит 3.5). Раскладка: адаптеры устройств и внешних систем (`snmp/`, `iconbit.py`, `onec_exchange.py`, `hostname_resolver.py`, `mac_lookup.py`, `qr_generator.py`, `boarding_pass.py`, `honest_sign.py`) → `app/adapters/`; предметная логика (`cartridge_*`, `poll_resilience.py`, `polling_orchestrator.py`, `mac_rediscovery.py`, `event_log.py`, `media_center.py`, `app_settings.py`, `smart_search.py`) → соответствующий `app/domains/*`. Двигать по одному модулю за коммит, без реэкспортов-заглушек | `app/services/` | Каталога `app/services` нет; тест границ обновлён |
| D6 | **Опрос устройств через общий шаблон.** `printer_polling`, `media_polling`, `computer_polling`, `cash_register_polling`, `switch_polling` повторяют: выборка → семафор → проба → state machine офлайна → запись → событие → инвалидация кэша. Выделить `PollCycle` (Template Method или композиция: `Prober` Protocol + общий раннер), чтобы каждый тип задавал только пробу и маппинг результата. Сохранить все эвристики (подсеть, circuit breaker, jitter) в раннере | `app/domains/inventory/*_polling.py`, `domains/operations/cash_register_polling.py`, `services/poll_resilience.py` | Новый тип устройства = один класс `Prober`; сверка на парке без расхождений |
| D7 | **Роутеры тонкие.** В `api/routes/printers.py`, `media_players.py`, `cash_registers.py`, `computers.py` одинаковый шаблон «список с фильтром + count + кэш + CRUD + уникальность IP». Вынести общий хелпер `list_page(session, model, filters, search_fields, skip, limit)` и `ensure_unique(...)` в `app/api/crud_helpers.py`; бизнес-проверки — в домен | `app/api/routes/*.py` | Роутеры < 250 строк, дублирование списков устранено |
| D8 | **Конфигурация по разделам.** `core/config.py` (339 строк, один класс `Settings`) разбить на вложенные модели pydantic-settings (`PollingSettings`, `AuthSettings`, `MLSettings`, `RemoteAccessSettings`, `QRSettings`…) с `env_nested_delimiter` или префиксами, сохранив имена переменных окружения. Прод `.env` не должен меняться | `app/core/config.py` | Все переменные из `.env.example` читаются, как раньше (тест на снапшот переменных) |
| D9 | **Фронт: декомпозиция больших страниц.** `RemoteAccessPage.tsx` (783), `CredentialsPage.tsx` (763), `Dashboard.tsx` (481), `MediaPlayerCard.tsx` (481) → контейнер (данные и хуки `useXxx`) + презентационные компоненты. Логику запросов — в `hooks/`, без `useQuery` внутри мелких компонентов, если данные уже есть у родителя | `frontend/src/pages`, `components` | Файлы < 300 строк, тесты страниц зелёные |
| D10 | **Типизированный API-клиент из OpenAPI** (`openapi-typescript` + тонкий fetch/axios-враппер) вместо ручных типов в `frontend/src/api/*.ts` (20 файлов). Генерация — скрипт `npm run gen:api` по `openapi.json` бэкенда; сгенерированный файл коммитится, CI проверяет актуальность (`git diff --exit-code`) | `frontend/src/api` | Ручные интерфейсы ответов удалены; расхождение с бэкендом ловится в CI |

---

## Фаза E — безопасность (по приоритету владельца)

Перенесено из аудита 4.1–4.2 без изменений, потому что не сделано:
HTTPS и `AUTH_COOKIE_SECURE=true`; access-token 15–30 минут в памяти вместо
`localStorage`, refresh в httpOnly-cookie; роли viewer / operator / admin;
показ секретов хранилища с повторным вводом пароля и записью в аудит. Делать
после фазы D1, когда ошибки и зависимости уже унифицированы.

---

## Порядок и оценки

| Фаза | Срок | Зависимости |
|---|---|---|
| A | 1–2 дня | — |
| B | 1–2 недели | A. B7 — после сверки на парке |
| C | 1–2 недели | A; C1 до D (типы упрощают рефакторинг) |
| D | 3–5 недель | C1. D3 → D4 → D6; D1 до D5 |
| E | по решению | D1 |

Внутри фаз порядок — по номерам. Вне этого плана ничего не рефакторить
«заодно»: найденное по ходу записывать отдельным пунктом в конец документа
(раздел «Находки»).

## Находки

_(заполняет исполнитель)_
