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

## Осталось (блокеры на пользователе)

| Что | Зачем | Кто |
|---|---|---|
| `RUSTDESK_API_TOKEN` в серверный `.env` | без него нет статусов «онлайн», пользователей консоли и книги адресов | пользователь: Settings → API tokens в веб-консоли, вписать, рестарт `backend`+`worker` |
| Свериться с реальным API консоли | пути `/api/admin/{user,peer,audit_conn,address_book}/list` сняты с живого бандла, но **write-пути книги адресов угаданы** (`POST /api/admin/address_book`) | после токена: временно `show-swagger: 1` в `~/rustdesk/conf/config.yaml`, сверить, вернуть `0`. Поправить `rustdesk_client.upsert/delete_address_book_entry` |
| Учётка для книги адресов | в lejianwen книга адресов пер-пользовательская — решить, под каким аккаунтом консоли пишем (личная vs общая с группой) | пользователь |
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
