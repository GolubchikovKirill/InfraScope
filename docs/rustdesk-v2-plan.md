# RustDesk в InfraScope — план доработки до рабочего состояния

Составлено 2026-09-02. Заказ: (1) заводить учётки для нескольких админов и
отдавать им адресную книгу всего парка, (2) деплоить клиент **из InfraScope**
тихо, не мешая работе на машине, (3) единый пароль подключения `kentdful`,
(4) в интерфейсе видеть, что машина реально готова к подключению.

Предыдущее состояние — [remote-access-hardening-plan.md](remote-access-hardening-plan.md)
(история) и [rustdesk-ksc-deployment.md](rustdesk-ksc-deployment.md) (раскатка).

## Статус реализации

| Раздел | Состояние |
|---|---|
| 0. Находки по API и документации | исследование закончено |
| 1. Архитектура деплоя (pull) | **сделано** |
| 2. Схема БД (миграция `d1e2f3a4b5c6`) | **сделано** |
| 3. Настройки | **сделано** |
| 4.1 `rustdesk_client` (оба заголовка, админский API) | **сделано** |
| 4.2 `service` (учётки, общая книга, `readiness`) | **сделано** |
| 4.3 `deploy_script` (bootstrap.ps1) | **сделано** |
| 4.4 Эндпоинты | **сделано** |
| 4.5 Worker | **сделано** |
| 5. Фронтенд | **сделано** — вкладки «Устройства/Админы/Подключения», чип готовности, модалка команды KSC, панель учёток |
| 6. Тесты бэкенда | **сделано** (`test_remote_access_service.py`, `test_remote_access_console.py`, `test_rustdesk_client.py`) |
| 6. Тесты фронтенда | **сделано** — 5 новых файлов, 29/29 файлов и 91/91 тест зелёные (`npx vitest run`) |
| 7. Выкат на прод | **задача пользователя** |

---

## 0. Что выяснили в исходниках консоли и документации RustDesk

Три находки, которые меняют архитектуру. Всё проверено по исходникам
`lejianwen/rustdesk-api` (ветка master) и официальной документации RustDesk.

### 0.1. Админский API консоли доступен — просто другой заголовок

`http/middleware/admin.go`:

```go
func BackendUserAuth() gin.HandlerFunc {
    token := c.GetHeader("api-token")            // <— не Authorization
    user, ut := service.AllService.UserService.InfoByAccessToken(token)
```

`http/middleware/rustauth.go` (клиентский API `/api/*`) читает
`Authorization: Bearer <token>`. **Оба** ищут одну и ту же строку в таблице
`user_tokens`. То есть один и тот же токен открывает обе поверхности, надо
только слать оба заголовка сразу. Прошлая сессия слала только `Bearer` и
сделала вывод, что `/api/admin/*` недоступен — вывод был неверный.

Дополнительно, `service/user.go` `Login()` делает `DB.Create(ut)` — новые
токены **добавляются**, старые не удаляются. Значит вход `admin` в веб-консоль
не убивает токен InfraScope (прежнее опасение тоже снято). Всё равно заводим
отдельного сервисного пользователя — но уже не из-за ротации, а ради аудита.

Что это открывает (`http/router/admin.go`, базовый путь `/api/admin`):

| Задача | Эндпоинт |
|---|---|
| Учётки | `POST /user/create`, `POST /user/updatePassword`, `POST /user/update`, `GET /user/list`, `GET /user/current` |
| Группы | `GET /group/list`, `POST /group/create` |
| Общие книги | `POST /address_book_collection/create`, `GET /address_book_collection/list` |
| Права на книгу | `POST /address_book_collection_rule/create` (`type` 1=юзер 2=группа, `rule` 1=чтение 2=чтение+запись 3=полный) |
| Записи книги | `GET /address_book/list`, `POST /address_book/create`, `POST /address_book/update`, `POST /address_book/delete` |
| Инвентарь пиров | `GET /peer/list` — **есть `version`, `os`, `cpu`, `memory`, `last_online_time`, `last_online_ip`, `uuid`** |
| Аудит подключений | `GET /audit_conn/list` |

`GET /api/peers` (клиентский) отдавал только `id + info{device_name,os,username}` —
поэтому `installed_version` в InfraScope никогда не заполнялся. С
`/api/admin/peer/list` заполнится.

### 0.2. Общая адресная книга умеет носить пароль устройства

`model/addressBook.go`:

```go
Password string `json:"password"` // shared ab password
Hash     string `json:"hash"`     // personal ab hash password
```

Запись в **общей** книге (`collection_id > 0`) хранит пароль устройства в поле
`password`. Значит: админ логинится в клиент своей учёткой → видит общую книгу
«InfraScope» → жмёт на машину → подключается без ввода пароля. Ровно то, что
нужно, и ровно то, чего не давала личная книга `admin` (`guid 1-1-0`), которую
пушили раньше.

Ограничение `batchCreate`: он раскладывает **один** пир по **многим**
пользователям (`user_ids`), причём при `len(user_ids) > 1` принудительно
обнуляет `tags` и `collection_id`. Для общей книги он не годится — используем
`address_book/create` + `address_book/update` по строкам (upsert по `row_id`
из `address_book/list?collection_id=…`).

Права раздаём **на группу**, а не на каждого пользователя: создаём группу
`InfraScope Admins` (`group/create`, `type=2` — общая), правило
`{collection_id, type: 2, to_id: <group_id>, rule: 1}`, и каждого нового админа
создаём с `group_id` этой группы. Новый админ получает книгу автоматически.

### 0.3. Тихая установка: MSI, а не `--silent-install`

RustDesk публикует MSI начиная с 1.3.x; для нашей закреплённой версии есть
`rustdesk-1.4.9-x86_64.msi` (проверено в релизе на GitHub). Параметры
([документация MSI](https://rustdesk.com/docs/en/client/windows/msi/)):

```
msiexec /i rustdesk-1.4.9-x86_64.msi /qn ^
        CREATESTARTMENUSHORTCUTS=N CREATEDESKTOPSHORTCUTS=N INSTALLPRINTER=N ^
        /l*v C:\ProgramData\InfraScope\rustdesk-msi.log
```

Почему это лучше текущего `rustdesk.exe --silent-install`:

* `--silent-install` **не возвращает управление** — инсталлятор превращается в
  работающее приложение (уже ловили эти грабли), из-за чего скрипт вынужден
  опрашивать наличие службы. `msiexec /qn` завершается кодом возврата.
* Ярлыки не создаются вообще, а не удаляются постфактум.
* Не ставится виртуальный принтер RustDesk (`INSTALLPRINTER=N`) — на кассах это
  лишняя запись в списке принтеров, которую увидит кассир.
* Апгрейд поверх — штатный (`msiexec /i <новый>.msi /qn`), с сохранением опций.

### 0.4. Опции «не мешать пользователю»

Ключи пишутся в `[options]` файла `RustDesk2.toml` (это уровень *User settings*,
OSS-клиент их читает). Полный список —
[Advanced Settings](https://rustdesk.com/docs/en/self-host/client-configuration/advanced-settings/).
Берём:

| Ключ | Значение | Зачем |
|---|---|---|
| `hide-tray` | `Y` | нет иконки в трее |
| `hide-stop-service` | `Y` | пользователь не остановит службу из UI |
| `allow-hide-cm` | `Y` | разрешает скрыть окно «идёт подключение» |
| `approve-mode` | `password` | без «нажмите Принять» на стороне кассира |
| `verification-method` | `use-permanent-password` | только постоянный пароль |
| `allow-logon-screen-password` | `Y` | **подключение к залоченной машине** (экран входа) |
| `disable-change-permanent-password` | `Y` | пароль не сменят с машины |
| `disable-change-id` | `Y` | ID не сменят |
| `hide-security-settings` / `hide-network-settings` / `hide-server-settings` | `Y` | не отредактируют сервер |
| `remove-preset-password-warning` | `Y` | нет жёлтой плашки про преднастроенный пароль |
| `hide-help-cards` | `Y` | нет плашек про UAC/разрешения |
| `enable-check-update` | `N` | клиент не лезет в интернет за обновлением |
| `enable-lan-discovery` | `N` | не светится в LAN-обнаружении |
| `direct-server` | `N` | только через наш hbbs |

**Порядок важен.** `disable-change-permanent-password=Y` блокирует
`rustdesk.exe --password`. Поэтому конфиг пишется в два прохода: установка →
базовый TOML без локов → задать пароль → проверить пароль → перезаписать TOML
уже с локами. Текущий `configure.ps1` локи не пишет вовсе, так что он не сломан —
но добавить их «в лоб» в существующий однопроходный блок значит получить машину
без пароля. Оба скрипта приводим к двухпроходной схеме.

`allow-hide-cm=Y` только *разрешает* скрытие; само окно прячет управляющая
сторона (в клиенте админа, в меню сессии). OSS-клиент всё равно рисует
небольшой индикатор — TOML-ключа, который его убирает, не существует. В
интерфейсе InfraScope это надо честно написать, а не обещать полную
невидимость.

---

## 1. Архитектура деплоя: InfraScope как источник, endpoint как инициатор

Прямой push с Linux-сервера (`impacket`/`wmiexec`) отвергнут ранее и остаётся
отвергнутым: он неотличим от lateral movement, и Kaspersky на парке его блокирует.
Вместо push делаем **pull**: InfraScope отдаёт всё (инсталлятор, конфиг,
пароль, скрипт), а запуск инициируется на самой машине — тем каналом, который
до неё уже дотягивается.

```
InfraScope                                     Машина в магазине
──────────                                     ─────────────────
GET  /remote-access/deploy/bootstrap.ps1  ───▶  powershell … | iex
POST /remote-access/deploy/config              ◀── {hostname}
     {id_server, key, rustdesk_id,        ───▶
      password, options[]}
GET  /remote-access/deploy/installer      ───▶  rustdesk-1.4.9-x86_64.msi (+sha256)
                                                msiexec /qn → TOML → --password
POST /remote-access/deploy/report         ◀───  {hostname, rustdesk_id, version,
                                                 state, detail}
```

Каналы запуска (все — одна и та же строка, InfraScope показывает её кнопкой
«Скопировать команду»):

1. **Kaspersky Security Center** — задача «Запуск скрипта» на группу устройств.
   Основной канал: KSC уже стоит на всём парке, работает по расписанию и
   доживается до включения машины.
2. **GPO computer startup script** — для машин вне KSC.
3. **`schtasks /S <host> /RU SYSTEM`** с админской рабочей станции — для точечной
   доустановки одной-двух машин.

InfraScope при этом владеет: версией инсталлятора, ключом сервера, ID,
паролем, набором опций, состоянием раскатки и адресной книгой. Меняется пароль
или опция — меняется только строка в БД, следующий прогон скрипта её применит;
пересобирать пакет KSC не нужно. Это главное отличие от текущей схемы, где
конфиг зашит в `rustdesk-ksc.json` внутри пакета.

### Безопасность pull-эндпоинтов

`/deploy/*` не проходят обычную авторизацию InfraScope (на машине нет сессии) —
их защищает общий секрет `RUSTDESK_DEPLOY_TOKEN` в заголовке
`X-InfraScope-Deploy-Token`. Требования, которые надо зафиксировать в README:

* токен генерируется `openssl rand -hex 32` и живёт только в `.env` на сервере;
* `/deploy/config` отдаёт пароль **только** для существующей строки устройства
  с `managed = true` — неизвестный hostname получает 404, а не дефолтный пароль;
* эндпоинты доступны только из LAN 10.10.98.0/23 и AmneziaWG 10.13.13.0/24
  (сервер и так без публичного IP, но правило стоит записать явно);
* каждый вызов пишется в лог с hostname и IP.

Пароль всё равно попадает на машину — иначе клиент не настроить; в схеме с KSC
он точно так же лежал в `rustdesk-ksc.json` внутри пакета. Разница в том, что
теперь он не разъезжается копиями по пакетам и ротируется из одного места.

---

## 2. Схема БД

Миграция `d1e2f3a4b5c6_remote_access_v2`.

### 2.1. `remoteaccessdevice` — новые колонки

| Колонка | Тип | Смысл |
|---|---|---|
| `deploy_state` | `varchar(16)`, default `unknown` | `unknown` → `pending` → `installed` → `configured` / `failed` |
| `deploy_detail` | `varchar(512)` null | последняя строка от скрипта (ошибка msiexec и т.п.) |
| `deploy_requested_at` | timestamptz null | когда в UI нажали «Развернуть» |
| `deploy_reported_at` | timestamptz null | когда скрипт отчитался |
| `ab_row_id` | int null | `row_id` записи в общей книге — чтобы делать update, а не create |
| `ab_password_pushed` | bool, default false | пароль в книге совпадает с текущим |

`deploy_state` возвращается ровно тот, что прислал скрипт. Никаких «наверное
установлено» — это тот же принцип, что уже применён для
`online` / `host_online`.

### 2.2. Новая таблица `remoteaccessconsoleaccount`

Учётки консоли RustDesk, которыми управляет InfraScope.

| Колонка | Тип |
|---|---|
| `id` | uuid pk |
| `username` | varchar(64) unique |
| `console_user_id` | int null — id в консоли |
| `display_name`, `email` | varchar null |
| `is_admin` | bool default false |
| `infrascope_user_id` | uuid null fk → `user.id` |
| `active` | bool default true |
| `book_shared` | bool default false — правило на общую книгу выдано |
| `last_synced_at`, `created_at`, `updated_at` | timestamptz |

**Пароль не хранится.** Он генерируется (или задаётся) при создании, уходит
в консоль и один раз возвращается в ответе API, чтобы админ увидел его в
интерфейсе и сохранил. Повторно узнать нельзя — только сбросить.

---

## 3. Настройки (`app/core/config.py` + `.env` на сервере)

```python
RUSTDESK_API_TOKEN: str = ""              # существует; теперь шлётся в ОБА заголовка
RUSTDESK_ADMIN_USERNAME: str = ""         # сервисный пользователь консоли
RUSTDESK_ADMIN_PASSWORD: str = ""         # — для авто-логина, если токен протух
RUSTDESK_DEFAULT_PASSWORD: str = "kentdful"
RUSTDESK_SHARED_BOOK_NAME: str = "InfraScope"
RUSTDESK_ADMIN_GROUP_NAME: str = "InfraScope Admins"
RUSTDESK_INSTALLER_KIND: str = "msi"      # msi | exe
RUSTDESK_INSTALLER_FILENAME: str = "rustdesk-1.4.9-x86_64.msi"
RUSTDESK_INSTALLER_SHA256: str = ""       # проверяется на машине перед запуском
RUSTDESK_PACKAGE_DIR: str = "/var/lib/infrascope/rustdesk"
RUSTDESK_DEPLOY_TOKEN: str = ""           # секрет для /deploy/*
RUSTDESK_PUBLIC_URL: str = ""             # как машина видит InfraScope (для скрипта)
```

`RUSTDESK_ADMIN_USERNAME`/`PASSWORD` дают самовосстановление: если токен
протух или его удалили, клиент делает `POST /api/admin/login` и продолжает
работать. Без них поведение прежнее — «консоль не подключена».

---

## 4. Backend

### 4.1. `rustdesk_client.py`

* `_headers()` → `{"Authorization": "Bearer <t>", "api-token": "<t>"}`.
* `_token()` — кеш в памяти: `RUSTDESK_API_TOKEN`, иначе логин под сервисным
  пользователем; при 401/403 сбрасывается и логин повторяется один раз.
* `_rows()` — распаковка админского конверта `{"code":0,"data":{"list":[…],"total":N}}`
  наравне с клиентским `{"data":[…]}`.
* Учётки: `list_console_users`, `create_console_user`, `set_console_user_password`,
  `update_console_user` (в т.ч. `status=2` — отключить).
* Группы: `list_groups`, `create_group`.
* Книги: `list_collections`, `create_collection`, `list_collection_rules`,
  `create_collection_rule`.
* Записи: `list_address_book_rows`, `create_address_book_row`,
  `update_address_book_row`, `delete_address_book_rows`.
* Инвентарь и аудит: `list_admin_peers`, `list_audit_connections`.
* Читающие вызовы деградируют в `[]`, пишущие — `HTTPException(502)` с текстом
  ответа консоли (как сейчас).

Удаление пользователя консоли **не реализуем** — тело запроса `user/delete`
неоднозначно, а консоль запрещает удалять последнего админа. Отключение
(`status = 2`) закрывает задачу и обратимо.

### 4.2. `service.py`

```
ensure_console_group()      -> group_id       группа InfraScope Admins
ensure_shared_book()        -> collection_id  общая книга + правило на группу
provision_account(...)      -> (row, password) создать учётку + положить в группу
reset_account_password(...) -> password
set_account_active(...)
sync_accounts(session)                        подтянуть /user/list в таблицу
push_shared_address_book(session, devices)    upsert строк с паролем и тегами
sync_from_console(session)                    + version/os/ip/last_online из admin peer list
deployment_config(dev)      -> dict           то, что отдаём машине
apply_deploy_report(...)                      отчёт скрипта -> deploy_state
readiness(dev)              -> str            единый статус для UI
```

`readiness(dev)`:

| Значение | Условие | Что показываем |
|---|---|---|
| `ready` | `deploy_state in (configured, verified)` и `online is True` | «Готово к подключению» (зелёный) |
| `installed_offline` | развёрнуто, но `online` не `True` | «Развёрнуто, машина офлайн» |
| `deploying` | `deploy_state == pending` | «Разворачивается» |
| `failed` | `deploy_state == failed` | «Ошибка», `deploy_detail` в подсказке |
| `not_deployed` | остальное | «Не развёрнуто» |

Отдельно в `DevicePublic` отдаём флаги-составляющие (`client_installed`,
`password_set`, `in_address_book`, `online`, `host_online`), чтобы карточка
могла показать, чего именно не хватает.

### 4.3. `deploy_script.py`

Рендер PowerShell-скрипта из шаблона. Скрипт:

1. Требует SYSTEM/админа, `$ErrorActionPreference='Stop'`, лог в
   `C:\ProgramData\InfraScope\rustdesk-configure.log`.
2. Тянет свой конфиг: `POST /deploy/config {hostname}` с токеном.
3. Если RustDesk уже нужной версии и конфиг совпадает — рапортует `configured`
   и выходит (идемпотентность, чтобы KSC мог гонять задачу по расписанию).
4. Скачивает MSI из `/deploy/installer`, сверяет sha256.
5. `msiexec /i … /qn CREATESTARTMENUSHORTCUTS=N CREATEDESKTOPSHORTCUTS=N INSTALLPRINTER=N`,
   проверяет код возврата.
6. `--install-service` если службы нет; останавливает службу.
7. Пишет `RustDesk.toml` (`id = '<rid>'`) и `RustDesk2.toml` (сервер, ключ,
   опции **без** локов) в оба конфиг-каталога
   (`ServiceProfiles\LocalService\…` и `System32\config\systemprofile\…`).
8. Запускает службу, ждёт, `rustdesk.exe --password <pw>`, проверяет что пароль
   лёг в `RustDesk.toml`.
9. Перезаписывает `RustDesk2.toml` уже с `disable-change-permanent-password=Y`
   и `disable-change-id=Y`.
10. Опционально AppLocker (запрет интерактивного запуска не-админам).
11. `POST /deploy/report` с итогом. В `finally` — рапорт `failed` с текстом
    исключения, чтобы InfraScope не остался с `pending` навсегда.

Существующий `rustdesk-ksc/configure.ps1` остаётся для варианта «пакет KSC без
сети до InfraScope», но его порядок операций чиним тем же образом.

### 4.4. Эндпоинты (`app/api/routes/remote_access.py`)

Учётки (superuser):

```
GET    /remote-access/accounts
POST   /remote-access/accounts              {username, display_name, email, is_admin, password?}
POST   /remote-access/accounts/{id}/reset-password
POST   /remote-access/accounts/{id}/disable | /enable
POST   /remote-access/accounts/sync
```

Общая книга (superuser):

```
POST   /remote-access/address-book/sync     {device_ids? | location? | source_kind?}  → в общую книгу
GET    /remote-access/address-book/status   имя книги, id, число записей, кому выдана
```

Деплой (superuser):

```
POST   /remote-access/devices/{id}/deploy        помечает pending, отдаёт команду для копирования
GET    /remote-access/deploy/command             одна строка для KSC/GPO
GET    /remote-access/deploy/bootstrap.ps1       (deploy-токен) сам скрипт
POST   /remote-access/deploy/config              (deploy-токен) конфиг машины
GET    /remote-access/deploy/installer           (deploy-токен) MSI
POST   /remote-access/deploy/report              (deploy-токен) отчёт
```

Старый `GET /devices/{id}/package` остаётся — он нужен для оффлайн-пакета KSC.

### 4.5. Worker

`tasks.remote_access_sync` (сейчас каждые 2 минуты) дополняется:
`sync_accounts` и `push_shared_address_book` для устройств, у которых
`in_address_book = false` или `ab_password_pushed = false`. Обе операции
идемпотентны и дешёвые.

---

## 5. Фронтенд — сделано

1. **`RemoteAccessPage.tsx`** — вкладки «Устройства» / «Админы» / «Подключения»
   (`app-tabbar`/`app-tab`, как на Dashboard). В таблице устройств колонка
   «RustDesk / хост» заменена на «Готовность» — чип из `readiness` с
   подсказкой (`deviceReadinessDetail`), собранной из `online`, `host_online`
   и `deploy_state`. Кнопка «Развернуть» на строке → `POST /devices/{id}/deploy`
   → общая модалка команды. Кнопка «Команда для KSC» в шапке открывает ту же
   модалку без привязки к устройству. Плашка про индикатор сессии RustDesk OSS —
   внизу таблицы устройств.
2. **`ConsoleAccountsPanel.tsx`** (вкладка «Админы») — список
   `remoteaccessconsoleaccount`, кнопки «Добавить», «Синхронизировать»,
   «Сбросить пароль», «Включить/Отключить» (отключение — через `useConfirm()`).
   Карточки статуса общей книги (`getAddressBookStatus`). Модалка создания и
   модалка сброса пароля показывают секрет **один раз**, с кнопкой копирования
   и текстом `note` от бэкенда.
3. **`DeployCommandModal.tsx`** — общая модалка с командой из
   `getDeployCommand()`, копированием и инструкцией «куда вставить»
   (KSC/GPO/schtasks); отдельно показывает предупреждение, если
   `RUSTDESK_DEPLOY_TOKEN`/`RUSTDESK_PUBLIC_URL` не заданы на сервере
   (`configured: false`).
4. **`RemoteAccessStatus.tsx`** — общий `ReadinessChip` +
   `deviceReadinessDetail`, чтобы подписи не расходились между страницей и
   карточками устройств.
5. **`RemoteAccessButtons.tsx`** — чип готовности вместо пары иконок; кнопка
   «Развернуть» вместо «Пакет KSC» как основное действие; оффлайн-пакет KSC
   остался как второстепенная иконка-кнопка (нужен для машин без сети до
   InfraScope, см. §6 в `rustdesk-ksc-deployment.md`).
6. `frontend/src/lib/relTime.ts` — общий хелпер относительного времени,
   вынесен из `RemoteAccessPage.tsx`.
7. `npx tsc --noEmit && npx vitest run` зелёные: **29/29 файлов, 91/91 тест**
   (было 24/68 до этой сессии).

Подписи статусов, чтобы не расходились между страницей и карточками:

| `readiness` | Подпись | Тон |
|---|---|---|
| `ready` | Готово к подключению | зелёный |
| `installed_offline` | Развёрнуто, машина офлайн | серый |
| `deploying` | Разворачивается | янтарный |
| `failed` | Ошибка развёртывания | красный, `deploy_detail` в подсказке |
| `not_deployed` | Не развёрнуто | серый-пунктир |

Отдельно стоит написать в интерфейсе, что «скрытый» режим убирает трей, ярлыки
и настройки, но **не** прячет индикатор активной сессии — этого RustDesk OSS не
умеет. Обещать полную невидимость нельзя.

---

## 6. Тесты

`tests/unit/domains/test_remote_access_service.py` дополняется:

* `readiness()` по всем пяти веткам;
* `apply_deploy_report` переводит состояние и заполняет `deploy_reported_at`;
* `deployment_config` не отдаёт конфиг для `managed = false` и для неизвестного
  hostname;
* рендер скрипта содержит `/qn`, `CREATEDESKTOPSHORTCUTS=N` и **не** содержит
  `disable-change-permanent-password` в первом TOML;
* `push_shared_address_book` делает update при наличии `ab_row_id` и create без него;
* `provision_account` не пишет пароль в БД.

Новый `tests/unit/domains/test_rustdesk_client.py` (httpx mock):

* оба заголовка уходят в запрос;
* 401 → один повтор после `admin/login`, потом 502;
* распаковка админского конверта `{"code":0,"data":{"list":[…]}}`.

Фронтенд — пять новых файлов рядом с компонентами/страницей:

* `RemoteAccessStatus.test.tsx` — подпись чипа для каждого значения `readiness`,
  текст подсказки собирается из online/host_online/deploy_state;
* `DeployCommandModal.test.tsx` — не запрашивает команду, пока модалка закрыта;
  показывает предупреждение при `configured: false`; копирует команду;
* `ConsoleAccountsPanel.test.tsx` — список + статус общей книги; создание
  показывает пароль один раз; отключение спрашивает подтверждение
  (`useConfirm()`) прежде чем звать API; логин валидируется на клиенте;
* `RemoteAccessButtons.test.tsx` — чип готовности на карточке; «Развернуть»
  вызывает `requestDeploy` и открывает модалку команды; оффлайн-пакет остаётся
  доступен отдельной кнопкой;
* `RemoteAccessPage.test.tsx` — переключение вкладок; ряд таблицы даёт нужный
  чип; «Команда для KSC» не трогает ни одно устройство; книга адресов
  недоступна и кнопка её пуша задизейблена, когда консоль лежит.

Одна деталь, которая иначе ломает тесты на мутациях: TanStack Query 5.90
передаёт в `mutationFn` второй (context) аргумент, поэтому `mutationFn: fn`
"поточечным" присваиванием (без обёртки) на рантайме безвреден, но
`toHaveBeenCalledWith(ожидаемыйАргумент)` в тесте увидит два аргумента и
упадёт. Все `mutationFn` в новом коде обёрнуты явной стрелочной функцией
(`mutationFn: (id) => requestDeploy(id)`), как уже было в `Dashboard.tsx`.

Прогон — как в CI:

```bash
uv run ruff check app tests && uv run pytest tests/unit -q
cd frontend && npx tsc --noEmit && npx vitest run
```

---

## 7. Порядок выката

1. Сгенерировать и положить в `.env` на сервере:
   `RUSTDESK_DEPLOY_TOKEN`, `RUSTDESK_PUBLIC_URL`, `RUSTDESK_ADMIN_USERNAME`,
   `RUSTDESK_ADMIN_PASSWORD`, `RUSTDESK_INSTALLER_SHA256`.
2. Положить `rustdesk-1.4.9-x86_64.msi` в `RUSTDESK_PACKAGE_DIR` на сервере,
   смонтировать каталог в `backend`.
3. `alembic upgrade head` (миграция едет в штатном деплое).
4. `./scripts/deploy-compose-prod.sh --no-pull`. Проверить, что `beat`
   и `worker` в `APP_SERVICES` — иначе новая синхронизация не поедет.
5. В UI: «Синхронизировать» → «Общая книга» → создать учётки админов.
6. Пилот: одна машина через `schtasks`, посмотреть `readiness` = `ready`.
7. KSC: задача «Запуск скрипта» на группу, расписание — вне бизнес-часов для касс.

Окно осторожности: авто-перезагрузка точек доступа в **04:30 и 16:30 UTC** —
перед рестартом `backend`/`worker`/`beat` проверять счётчик задач
`ap_auto_reboot_switch` в логах воркера за последние 20 минут.

---

## 8. Что осознанно не делаем

| Отвергнуто | Почему |
|---|---|
| Push с Linux-сервера (`impacket`/`wmiexec`) | неотличим от lateral movement, блокируется Касперским на парке |
| Свой Windows-агент InfraScope | нужен стабильный доменный хост и учётка; KSC уже делает это |
| Личная книга `admin` (`guid 1-1-0`) | видна только тому, кто логинится как `admin`; заменяется общей книгой |
| `POST /address_book/batchCreate` для общей книги | при `len(user_ids)>1` обнуляет теги и `collection_id` |
| Удаление учёток консоли из InfraScope | тело `user/delete` не подтверждено; хватает отключения |
| Обещание полной невидимости клиента | OSS-клиент рисует индикатор сессии, TOML-ключа против него нет |

---

## Источники

* [RustDesk MSI](https://rustdesk.com/docs/en/client/windows/msi/) — параметры `msiexec`
* [RustDesk Client Deployment](https://rustdesk.com/docs/en/self-host/client-deployment/) — `--config`, `--password`, MSI вместо `--silent-install`
* [RustDesk Advanced Settings](https://rustdesk.com/docs/en/self-host/client-configuration/advanced-settings/) — все ключи `[options]`
* [lejianwen/rustdesk-api](https://github.com/lejianwen/rustdesk-api) — `http/router/admin.go`, `http/middleware/admin.go`, `model/addressBook.go`, `model/user.go`
