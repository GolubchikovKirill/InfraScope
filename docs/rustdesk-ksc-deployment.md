# Раскатка RustDesk на парк

Полное описание архитектуры и обоснование решений — [rustdesk-v2-plan.md](rustdesk-v2-plan.md).
Здесь — практическая инструкция.

InfraScope **не выполняет команды на машинах**: запуск с Linux-сервера
(`impacket`/`wmiexec`) неотличим от lateral movement и блокируется самим
Касперским. Вместо этого машина **сама забирает** у InfraScope скрипт,
инсталлятор и свой конфиг. Триггером служит любой канал, который до неё уже
дотягивается: KSC, GPO или `schtasks`.

---

## 1. Что настроить на сервере один раз

В `~/InfraScope/.env`:

```bash
REMOTE_ACCESS_ENABLED=true
RUSTDESK_API_URL=http://10.10.99.24:21114
RUSTDESK_ADMIN_USERNAME=infrascope        # сервисная учётка консоли
RUSTDESK_ADMIN_PASSWORD=...               # её пароль
RUSTDESK_ID_SERVER=10.10.99.24
RUSTDESK_RELAY_SERVER=10.10.99.24
RUSTDESK_KEY=oRNmXpA+by3KIjdNCcCacnNJGQWMutQdiqgUevKs4FU=

RUSTDESK_DEFAULT_PASSWORD=kentdful        # единый пароль подключения парка
RUSTDESK_PUBLIC_URL=http://10.10.99.24:8000   # как машина видит InfraScope
RUSTDESK_DEPLOY_TOKEN=$(openssl rand -hex 32) # секрет для /deploy/*
RUSTDESK_INSTALLER_FILENAME=rustdesk-1.4.9-x86_64.msi
RUSTDESK_INSTALLER_VERSION=1.4.9
RUSTDESK_INSTALLER_SHA256=...             # sha256sum скачанного MSI
RUSTDESK_PACKAGE_DIR=/var/lib/infrascope/rustdesk
```

Положить инсталлятор и смонтировать каталог в контейнер `backend`:

```bash
sudo mkdir -p /var/lib/infrascope/rustdesk
cd /var/lib/infrascope/rustdesk
sudo curl -LO https://github.com/rustdesk/rustdesk/releases/download/1.4.9/rustdesk-1.4.9-x86_64.msi
sha256sum rustdesk-1.4.9-x86_64.msi        # значение -> RUSTDESK_INSTALLER_SHA256
```

Без `RUSTDESK_DEPLOY_TOKEN` все маршруты `/remote-access/deploy/*` отвечают
`503` — незаконфигуренная установка не должна раздавать пароли парка.

---

## 2. Команда для раскатки

InfraScope → «Удалённый доступ» → «Команда развёртывания» (или
`GET /api/v1/remote-access/deploy/command`). Одна строка вида:

```
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$c=New-Object Net.WebClient; $c.Headers.Add('X-InfraScope-Deploy-Token','<токен>'); iex $c.DownloadString('http://10.10.99.24:8000/api/v1/remote-access/deploy/bootstrap.ps1')"
```

Она одинакова для всех машин: скрипт сам спрашивает у InfraScope, кем ему быть,
по имени машины. Пароль или опция поменялись — команда та же, конфиг новый.

### Kaspersky Security Center (основной канал)

**Задачи → Создать → «Запуск скрипта» (или «Выполнение команды»)**

* Команда: строка выше.
* Учётная запись: **SYSTEM** (нужны права на службу, конфиг и AppLocker).
* Область: группа администрируемых устройств.
* Расписание: **кассы — вне бизнес-часов**, отдельной задачей.
* «Запускать пропущенные задачи» — включить: в 08:00 парк ещё выключен, задача
  доедет при включении.

Скрипт идемпотентен: если нужная версия уже стоит и конфиг совпадает, он
отчитается `configured` и выйдет, не переустанавливая ничего. Поэтому задачу
можно вешать на расписание, а не гонять руками.

### GPO (машины вне KSC)

Computer Configuration → Policies → Windows Settings → Scripts → Startup →
PowerShell Scripts, той же строкой.

Важно: ~69 из ~103 машин лежат в контейнере `CN=Computers`, на который GPO не
линкуется. Рабочий вариант — GPO на корень домена с фильтрацией по группе
безопасности (`SG-RustDesk-Targets`), а не перенос компьютеров в OU.

### Точечно, одна-две машины

```
schtasks /S <host> /RU SYSTEM /SC ONCE /ST 00:00 /TN InfraScopeRustDesk /TR "<команда>" /F
schtasks /S <host> /Run /TN InfraScopeRustDesk
```

WinRM на большинстве машин парка закрыт, SMB + `schtasks` работает.

---

## 3. Что делает скрипт на машине

1. Спрашивает свой конфиг: `POST /deploy/config {hostname}`. Неизвестный или
   `managed = false` хост получает `404` — пароль не отдаётся.
2. Если версия уже нужная — рапортует и выходит.
3. Скачивает MSI из `/deploy/installer`, сверяет sha256.
4. `msiexec /i … /qn CREATESTARTMENUSHORTCUTS=N CREATEDESKTOPSHORTCUTS=N INSTALLPRINTER=N`
   — тихо, с кодом возврата, без ярлыков и без виртуального принтера.
5. Ставит службу, пишет `RustDesk.toml` (ID) и `RustDesk2.toml` (сервер, ключ,
   опции) в оба конфиг-каталога службы.
6. Задаёт постоянный пароль и **проверяет**, что он лёг в файл.
7. Перезаписывает `RustDesk2.toml` с блокировками
   (`disable-change-permanent-password`, `disable-change-id`) — только после
   пароля, иначе `--password` становится пустышкой.
8. Убирает ярлыки, при `block_outgoing` добавляет правило AppLocker.
9. `POST /deploy/report` с результатом.

Лог на машине: `C:\ProgramData\InfraScope\rustdesk-configure.log`
(и `rustdesk-msi.log` рядом).

---

## 4. Проверка

В InfraScope на странице «Удалённый доступ» устройство должно перейти в
**«Готово к подключению»**. Этот статус требует двух вещей одновременно:

* машина отчиталась `configured` (скрипт применил конфиг), **и**
* консоль RustDesk видит клиента онлайн.

Если стоит «Развёрнуто, машина офлайн» — конфиг применён, но клиент до сервера
не достучался (машина выключена, или сеть). «Ошибка» — в подсказке текст от
скрипта.

---

## 5. Ротация пароля

1. Карточка устройства → «Ротировать пароль» (или сменить
   `RUSTDESK_DEFAULT_PASSWORD` для всего парка).
2. Строка в общей адресной книге помечается устаревшей и переедет при следующей
   синхронизации (раз в 2 минуты воркером).
3. На саму машину пароль попадёт при следующем прогоне задачи KSC — команда та
   же, перекатывать пакет не нужно.

---

## 6. Оффлайн-вариант: пакет KSC без сети до InfraScope

Если машина не видит InfraScope по HTTP, остаётся старая схема: пакет с
[`rustdesk-ksc/configure.ps1`](../rustdesk-ksc/configure.ps1) и
`rustdesk-ksc.json` внутри.

**Администрирование → Хранилища → Инсталляционные пакеты → Создать**

1. Тип: «для программы, указанной пользователем».
2. Файл: `rustdesk-1.4.9-x86_64.msi`.
3. Параметры запуска: `/qn CREATESTARTMENUSHORTCUTS=N CREATEDESKTOPSHORTCUTS=N INSTALLPRINTER=N`
4. Дополнительные файлы: `configure.ps1` и `rustdesk-ksc.json`.
5. После установки: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "configure.ps1"`

Готовый `rustdesk-ksc.json` для конкретной машины:
`GET /api/v1/remote-access/devices/{id}/package`.

Минус этого пути: конфиг зашит в пакет, поэтому смена пароля требует пересборки
пакета, а InfraScope не узнает результат установки — устройство останется в
статусе по данным консоли, без отчёта от машины.

## Раскатка с рабочей станции админа: Windows 7 и Windows 10, без перезагрузки

`rustdesk-ksc/Push-RustDesk.ps1` — то, чем раскатывали парк вручную. Запускается
**на машине админа** (не на сервере InfraScope: сервер сознательно ничего не
исполняет на парке, см. docstring в `app/domains/remote_access/deploy_script.py`)
и ходит по тому, что у админа уже есть: админ-шара `C$` и WMI/DCOM. Ни WinRM,
ни PsExec, ни задачи планировщика, ни служб на целевой машине не создаётся.

Зачем рядом с pull-схемой: pull-скрипту нужен TLS 1.2 до InfraScope, а Windows 7
с PowerShell 2.0 / .NET 2.0 его не умеет; плюс pull нужен триггер (KSC / GPO).

```powershell
cd rustdesk-ksc
copy rustdesk-ksc.example.json rustdesk-ksc.json   # вписать key и пароль
# положить в папку packages: rustdesk-1.4.9-x86_64.msi и rustdesk-1.4.9-x86-sciter.exe

.\Push-RustDesk.ps1 -ComputerName VNK-KKM-3301,VNA-KKM-701          # профиль client
.\Push-RustDesk.ps1 -ComputerName VNK-ITD-SA04 -Profile admin       # рабочая станция инженера
.\Push-RustDesk.ps1 -ListFile .\targets.txt -DryRun                 # только разведка
```

Что делает на каждой машине: определяет ОС по WMI и выбирает установщик —
Windows 10/11 x64 → MSI (`msiexec /qn /norestart`), Windows 7 или 32-бит →
32-битная sciter-сборка (`--silent-install`); Windows XP пропускает (RustDesk там
не работает). Копирует `endpoint/Install-RustDesk.ps1`, конфиг профиля и установщик
в `C:\Windows\Temp\RustDesk-Deploy`, запускает через `Win32_Process.Create`, ждёт,
при обрыве RPC (бывает на Windows 7) перезапускает один раз, проверяет службу и
удаляет папку (`-KeepFiles` оставляет).

**Перезагрузка не нужна и не инициируется**: MSI идёт с `/norestart` (коды 0 и
3010 = успех), флаг «ожидает перезагрузки» игнорируется, WMF / .NET / Windows
Update не ставятся. Скрипт на машине написан на синтаксисе PowerShell 2.0 —
Windows 7 без WMF 5.1 запускает его как есть (`tests/unit/domains/test_rustdesk_endpoint_scripts.py`
следит и за этим, и за отсутствием любых команд перезагрузки).

Профили — это три флага в `rustdesk-ksc.json`, которые утилита переопределяет:

| Профиль | hidden | unattended | Для чего |
|---|---|---|---|
| `client` (по умолчанию) | да | да | кассы, киоски, офисные ПК: трей скрыт, вход только по постоянному паролю |
| `admin` | нет | нет | рабочие станции инженеров (ITD-SA*): трей виден, подтверждение на месте, без пароля и блокировок |

Известные грабли, которые скрипт обходит: MSI поверх существующей установки может
оставить файлы без службы RustDesk — скрипт регистрирует службу
(`rustdesk.exe --install-service`); повторный запуск «с нуля» не меняет ID, пока
служба не пересоздаст `enc_id`, поэтому скрипт пишет ID и убирает `enc_id` до
запуска службы; лишние UI/tray-процессы нулевой сессии после WMI-запуска закрываются.

