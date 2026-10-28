# InfraScope — контекст для Claude

Retail IT monitoring: принтеры, свитчи, точки доступа, камеры, кассы,
компьютеры, медиаплееры примерно в 30 магазинах. Полная архитектура,
переменные окружения и штатные операционные команды — в [README.md](README.md).
Этот файл — только то, что README не покрывает: как сюда безопасно
попадать, куда что реально коммитить, и о какие грабли уже спотыкались.

## Топология git — ловушка №1

Локальный `origin` — это **сервер деплоя**, не GitHub:

```
origin  →  infrascope-server:~/InfraScope   (SSH alias, см. ниже)
```

На сервере, в свою очередь, `origin` смотрит на
`https://github.com/GolubchikovKirill/InfraScope.git`, но пуш оттуда не
проходит — учётных данных GitHub там нет (`could not read Username for
'https://github.com'`). Коммиты доходят до сервера и там останавливаются;
GitHub этим путём не обновляется, пока пользователь не даст туда доступ
сам.

**Правило: `git fetch origin` перед любой правкой, не после.** Дерево на
`D:\Main Files\InfraScope` тихо отстаёт — 17 августа 2026 оно оказалось на
17 коммитов позади с несохранёнными дублями уже сделанной наверху работы
(включая правку той же шапки свитча, что чинил кто-то другой). Если дерево
уже грязное и отстало: сохранить diff (`git diff > patch`), откатить файлы,
которые уже есть выше по течению (`git checkout HEAD -- <файлы>` —
предварительно сверить `git diff --stat HEAD origin/<branch> -- <файлы>`,
трогал ли их апстрим вообще), затем `git merge --ff-only`.

## Ветки

`main` — прод, `vnk-dev` — разработка: работа идёт в `vnk-dev`, в `main` —
только через PR `vnk-dev → main` с зелёным CI. Ветки `v2/vnk_deploy` и
`v2/dev` остаются действующими ветками проекта, их не удалять.
План текущих доработок — `docs/development-plan-2026-10.md`.

## Как попасть на прод

```
Host: 10.10.99.24     (сервер, где живёт вся Docker-платформа)
SSH alias: infrascope-server   →  C:\Users\GolubchikovKA\.ssh\config
```

Alias уже настроен на этой машине под пользователем `golubchikovka`:
`ssh infrascope-server` подключается без дополнительных флагов. Ключ
Claude-сессий — `~/.ssh/infrascope_codex`, отдельный от личного ключа
пользователя (`infrascope_server_key`, для PyCharm/WinSCP/PuTTY) — их
специально не смешивают, чтобы при разборе инцидента было видно, кто
заходил: автоматизация или человек.

Секреты (SQL-логины для генерации QR, ONEC-токены и т.д.) живут только в
`~/InfraScope/.env` на сервере, не в репозитории и не в этом файле.

## Тесты и деплой

Локально `uv` на самой Windows-машине работать умеет (`.venv` там уже
настроен), но `uv` **не установлен на самом сервере-хосте** — только внутри
контейнеров. `POSTGRES_SERVER=db` и `REDIS_URL=redis://redis:6379` — это
имена сервисов внутри Docker-сети, недоступные напрямую с хоста. Поэтому
`scripts/quality-gate.sh` (тот же `uv run ruff check` + `uv run pytest
tests`, что гоняет CI) нельзя просто запустить на сервере командой из
`ssh` — нужен контейнер с `uv` внутри той же docker-сети, что `db`/`redis`.

Рабочий паттерн, подтверждённый на практике:

```bash
# 1. sync правок на сервер (scp/tar, не git push — см. топологию выше)
# 2. на сервере: временный test-builder на базе Dockerfile-стадии `builder`
cat > docker-compose.test-override.yml <<'EOF'
services:
  test-builder:
    build: {context: ., target: builder}
    image: infrascope-test-builder:latest
    working_dir: /app
    entrypoint: []
    networks: [internal]        # обязательно — иначе коллизия подсетей
    volumes:
      - ./app:/app/app:ro
      - ./tests:/app/tests:ro
EOF
docker compose -f docker-compose.yml -f docker-compose.test-override.yml build test-builder
docker compose -f docker-compose.yml -f docker-compose.test-override.yml run --rm test-builder \
  sh -c 'uv sync --frozen --python /usr/local/bin/python && /app/.venv/bin/python -m pytest tests/unit -q'
# 3. cleanup: rm docker-compose.test-override.yml && docker rmi infrascope-test-builder:latest
```

`uv sync` нужен **в каждом запуске** — образ `test-builder` без него не
содержит dev-зависимостей (`pytest-asyncio` и т.п.) и падает на несвязанных
тестах. Пересобирать `test-builder` перед каждым `run`, если менялись
исходники — `docker compose run` иначе использует старый образ.

Сам деплой (после зелёных тестов) — уже готовый скрипт, ничего
изобретать не нужно:

```bash
./scripts/deploy-compose-prod.sh          # обновление без пересоздания БД
./scripts/deploy-compose-prod.sh --clean  # чистые контейнеры/сети, БД цела
```

## Опасное окно — автоперезагрузка точек доступа

AP auto-reboot automation запускается в **04:30 и 16:30 UTC**. Перед
рестартом `backend`/`worker`/`beat` проверять, что нет задач в полёте:

```bash
docker compose logs worker --since 20m | grep -c 'ap_auto_reboot_switch\['
```

Ноль — можно рестартовать. Не ноль — подождать или явно предупредить
пользователя, что перезапуск оборвёт цикл перезагрузки точки на месте.

## Коммиты

Длинные commit-message пишутся в скретч-файл, `scp` на сервер во
временный `/tmp/cN.txt`, `git commit -F`, затем файл удаляется. Прямая
подстановка многострочного текста через `ssh "git commit -m ..."`
регулярно бьётся об экранирование кавычек.
