# RustDesk (remote_access) — статус

Обновлено 2026-09-02. **Раскатка клиента переведена на Kaspersky Security
Center** — Windows-агент и очередь задач убраны (коммит "drop deploy queue").
Полное руководство по KSC: [rustdesk-ksc-deployment.md](rustdesk-ksc-deployment.md).

Почему не агентом из приложения: удалённый запуск с Linux-сервера
(`impacket`/`wmiexec`) неотличим от lateral movement и блокируется самим
Касперским на парке. KSC — родной путь и уже управляет всеми машинами.

Проверять после правок:
```bash
cd frontend && npx tsc --noEmit && npx vitest run
uv run ruff check app tests && uv run pytest tests/unit -q
```

---

## Что теперь делает InfraScope

- **Инвентарь → устройства.** `seed_from_inventory` мирроит все кассы,
  компьютеры и медиаплееры типа `nettop` в `remoteaccessdevice`.
- **Желаемый конфиг на устройство.** `rustdesk_id` (по hostname), пароль,
  `hidden`/`block_outgoing`/`unattended`. Отдаётся для KSC:
  `GET /remote-access/devices/{id}/package` → ключи 1:1 для `rustdesk-ksc.json`.
- **Статусы из консоли.** `sync_from_console` тянет peer list → `online`,
  `logged_in_user`, `installed_version`, `last_seen_at`. Отдельно
  `host_online`/`host_last_seen_at` — из собственного пуллинга InfraScope
  (пингуется ≠ RustDesk на связи).
- **Книга адресов.** `POST /remote-access/address-book/sync` проталкивает
  управляемые устройства в консоль с тегами `[класс, точка]`. Кнопка «В книгу
  адресов» на странице + иконка на карточке.
- **Карточки товаров.** Кнопка «Подключиться» (deep link), «Настроить»
  (ID + пароль), «Пакет KSC» (готовый `rustdesk-ksc.json`).

---

## Консоль: как устроена авторизация (выяснено 2026-09-02)

- Бирер для REST — это **JWT из `POST /api/login`** (`{username,password}` →
  `access_token`, начинается с `eyJ`). Значение из таблицы `user_tokens` (то, что
  показывает `_admin` в UserToken) — **не** бирер, по нему `401`.
- Работает только **клиентский API** `/api/*` (`/api/peers`, `/api/users`,
  `/api/ab`). `/api/admin/*` этим токеном не открыть — админка использует свою
  сессию. `rustdesk_client.py` переписан на `/api/*`; лог подключений
  (`/api/audit/conn`) — только в админке, будет пустым.
- **Каждый вход (веб-консоль ИЛИ `/api/login`) ротирует токен и убивает
  предыдущий.** Один токен в `.env` проживёт ровно до следующего входа `admin`
  в веб-консоль. → нужен **отдельный сервисный пользователь** консоли
  (`infrascope`, admin), под которым в веб никто не логинится.
- `token-expire` / `jwt.expire-duration` в `~/rustdesk/conf/config.yaml` подняты
  до `87600h` (10 лет). Бэкап: `config.yaml.bak-token-expire-*`.

## Осталось (блокеры на пользователе)

| Что | Зачем | Кто |
|---|---|---|
| Завести пользователя консоли `infrascope` (admin) | чтобы токен InfraScope не убивался при каждом входе `admin` в веб | пользователь: консоль → System → UserManage → Add |
| `RUSTDESK_API_TOKEN` = `access_token` этого юзера в серверный `.env` | статусы «онлайн», пользователи, книга адресов | `ssh infrascope-server 'curl -s http://10.10.99.24:21114/api/login -H "Content-Type: application/json" -d ...'`, вписать, рестарт `backend`+`worker` |
| Свериться с write-API книги адресов | `POST /api/ab` (legacy blob `{data:"<json>"}`) — форма peer'а ещё не подтверждена (400 на разных попытках) | после токена: `show-swagger: 1`, сверить, вернуть `0` |
| Книга адресов: личная vs общая | `/api/ab` — **личная** книга того аккаунта, под которым InfraScope. Техники видят её, только если логинятся тем же аккаунтом. Иначе нужна shared-книга (`address_book_collections`) | пользователь: решить, под каким аккаунтом заходят техники |
| Собрать пакет(ы) KSC | 1 пакет = 1 пароль; нужны разные по классам — 3 пакета | пользователь по [rustdesk-ksc-deployment.md](rustdesk-ksc-deployment.md) |

---

## История (сделано)

- **Инвентарь — 3 источника** + `source_kind` + `cash_register_id` (миграция `f7e8d9c0b1a2`).
- **Честные статусы** — `host_online` отдельно от `online` (миграция `b8c9d0e1f2a3`).
- **Разворот на KSC** — убраны `RemoteAccessDeployJob`, Windows-агент,
  `deploy_state`/`deploy_detail`/`last_deployed_at`/`last_error`/`password_confirmed_at`;
  добавлен `in_address_book` (миграция `c9d0e1f2a3b4`). Добавлены `rustdesk-ksc/`
  (configure.ps1 + пример конфига) и руководство.
- **Пути консольного API** переписаны на `/api/admin/*` (read-пути подтверждены).
