# RustDesk (remote_access) — история

Актуальные документы:

* **[rustdesk-v2-plan.md](rustdesk-v2-plan.md)** — архитектура, находки по API
  консоли и документации RustDesk, схема БД, эндпоинты, что делает фронт.
* **[rustdesk-ksc-deployment.md](rustdesk-ksc-deployment.md)** — практическая
  инструкция по раскатке.

Этот файл оставлен как журнал: тут видно, какие выводы были сделаны раньше и
какие из них потом оказались неверными.

---

## Что делает InfraScope сейчас

- **Инвентарь → устройства.** `seed_from_inventory` мирроит все кассы,
  компьютеры и медиаплееры типа `nettop` в `remoteaccessdevice`.
- **Желаемый конфиг на устройство.** `rustdesk_id` (по hostname), пароль,
  `hidden`/`block_outgoing`/`unattended`.
- **Раскатка pull-моделью.** Машина сама забирает скрипт, MSI и свой конфиг
  (`/remote-access/deploy/*`) и отчитывается о результате. Триггер — KSC, GPO
  или `schtasks`.
- **Учётки инженеров.** `POST /remote-access/accounts` заводит логин в консоли
  RustDesk в группе `InfraScope Admins`; пароль показывается один раз.
- **Общая адресная книга.** Одна коллекция с паролями устройств, расшаренная на
  группу — каждый инженер видит весь парк без персонального пуша.
- **Статусы.** `deploy_state` от самой машины, `online` из консоли,
  `host_online` из пуллинга InfraScope; сводится в `readiness`.

---

## Ревизия ранних выводов (2026-09-02)

Три вывода прошлых сессий были неверны и стоили функциональности:

| Тогда считали | На самом деле |
|---|---|
| «`/api/admin/*` не открыть API-токеном, только сессией админки» | Открывается — но заголовком `api-token`, а не `Authorization: Bearer`. Слали не тот заголовок. См. `http/middleware/admin.go`. |
| «Каждый вход ротирует токен и убивает предыдущий» | `UserService.Login()` делает `DB.Create(ut)` — токены добавляются, старые живут. Вход `admin` в веб-консоль токен InfraScope не ломает. |
| «Книгу адресов можно пушить только личную (`guid 1-1-0`)» | Через админский API есть общие коллекции (`address_book_collection`) с правилами доступа на пользователя или группу, и запись в них несёт пароль устройства. |

Верным остался вывод про раскатку: удалённый запуск с Linux-сервера
(`impacket`/`wmiexec`) неотличим от lateral movement и блокируется Касперским.
Отсюда pull-модель вместо push.

---

## История (сделано)

- **Инвентарь — 3 источника** + `source_kind` + `cash_register_id` (миграция `f7e8d9c0b1a2`).
- **Честные статусы** — `host_online` отдельно от `online` (миграция `b8c9d0e1f2a3`).
- **Разворот на KSC** — убраны `RemoteAccessDeployJob`, Windows-агент,
  `deploy_state`/`deploy_detail`/`last_deployed_at`/`last_error`/`password_confirmed_at`
  (миграция `c9d0e1f2a3b4`). Добавлен `in_address_book`.
- **v2** (миграция `d1e2f3a4b5c6`) — `remoteaccessconsoleaccount`,
  `ab_row_id`/`ab_password_pushed`, `deploy_state` возвращён, но теперь его
  **сообщает сама машина**, а не выводит планировщик задач.

## Консоль: авторизация (проверено 2026-09-02)

- Токен — строка из таблицы `user_tokens`. Получается через
  `POST /api/admin/login` (`{username,password}` → `data.token`) или
  `POST /api/login`. Одна и та же строка работает на обеих поверхностях.
- `/api/*` читает `Authorization: Bearer <t>`, `/api/admin/*` читает
  `api-token: <t>`. `rustdesk_client` шлёт оба заголовка всегда.
- `token-expire` / `jwt.expire-duration` в `~/rustdesk/conf/config.yaml` подняты
  до `87600h` (10 лет). Плюс `RUSTDESK_ADMIN_USERNAME`/`PASSWORD` в `.env` —
  тогда протухший токен InfraScope перевыпустит сам.

Проверять после правок:
```bash
uv run ruff check app tests && uv run pytest tests/unit -q
cd frontend && npx tsc --noEmit && npx vitest run
```
