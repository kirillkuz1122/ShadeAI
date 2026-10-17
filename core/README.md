# Shade Core

Бэкенд Shade AI на FastAPI. [Контракт API](../docs/api-spec.md), [архитектура](../docs/architecture.md), [задачи](../docs/mvp.md).

## Локальная установка и запуск

Команды выполняются из корня репозитория. Нужен Python 3.11 или новее; чистая установка проверена на Python 3.11.

```bash
cd core
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m app.setup
# При необходимости отредактируйте HA_BASE_URL и HA_TOKEN в .env.
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- Health: `curl http://localhost:8000/api/v1/health` — доступен без ключа.
- Swagger UI: `http://localhost:8000/docs`.
- Защищённые запросы требуют `Authorization: Bearer <SHADE_API_KEY>`.
- Работа Home Assistant и LLM не требуется для старта. Без HA health сообщает `ha_connected: false`; LLM пока заглушка.

`requirements.txt` содержит зависимости приложения, `requirements-dev.txt` добавляет pytest и ruff. Прямые зависимости закреплены на проверенных версиях; транзитивные зависимости полностью не зафиксированы. LLM-зависимости остаются отдельно в `requirements-llm.txt`, для запуска скелета они не нужны.

## Настройки и ключ

Настройки читаются из `.env` в рабочем каталоге, переменные окружения имеют приоритет. Запускайте сервер из `core/`.

`python -m app.setup` копирует шаблон `.env.example`, создаёт локально случайный ключ через `secrets.token_urlsafe(32)` и устанавливает права файла `600`. Команда не выводит ключ. Если `.env` уже существует, остальные параметры сохраняются, корректный ключ не заменяется. Пустое значение и известные заглушки `change-me` / `change-me-to-long-random-string` заменяются случайным ключом.

| Переменная | Назначение |
| :--- | :--- |
| `SHADE_API_KEY` | Обязательный Bearer-ключ: не менее 32 ASCII-символов без пробелов; имя `API_KEY` не используется |
| `DB_URL` | По умолчанию `sqlite+aiosqlite:///./shade.db` |
| `HA_BASE_URL` | Адрес локального HA; по умолчанию `http://127.0.0.1:8123` |
| `HA_TOKEN` | Токен HA; по умолчанию пустой |
| `LLM_MODEL_PATH` | Путь к GGUF для будущего подключения LLM |
| `CORS_ORIGINS` | Если задан, JSON-массив адресов; по умолчанию разрешены localhost/127.0.0.1:5173 |

Можно создать файл по другому пути: `python -m app.setup --env-file /путь/к/.env`. Это только путь для настройки: сервер по-прежнему читает `.env` из своей рабочей директории или переменные окружения.

Если ключ отсутствует или некорректен, Core прекращает запуск и предлагает выполнить настройку. Произвольный некорректный ключ команда настройки не перезаписывает: исправьте его вручную либо очистите значение `SHADE_API_KEY` и повторите команду. Символические ссылки вместо файла настройки не принимаются. Если в окружении задан старый/неверный `SHADE_API_KEY`, исправьте или удалите эту переменную: она перекрывает `.env`.

Для настройки веба скопируйте ключ из локального `.env` в поле интерфейса. Настройка Bearer в Android ещё запланирована в TASK-09.

## Миграции БД

Таблицы теперь управляются [Alembic](migrations/): `0001_legacy_schema` фиксирует прежние notifications_raw/events_log, `0002_device_states` добавляет последние состояния сущностей HA. Core выполняет `upgrade head` в lifespan до приёма запросов. Новая БД создаётся миграциями; `create_all` больше не вызывается. Для первого обновления существующей БД сначала остановите Core и сделайте резервную копию.

Команды из `core/`, с тем же окружением и `.env`, что у сервера:

```bash
python -m alembic upgrade head
python -m alembic current
python -m alembic check
```

Адрес берётся из `DB_URL` настроек Core, в alembic.ini второго адреса нет. Путь по умолчанию — `core/shade.db` при запуске из `core/`. `current` показывает `0002_device_states (head)`, `check` проверяет соответствие модели и схемы. Настройка SHADE_API_KEY требуется и для этих команд. Режим `--sql` не поддерживается: первая миграция должна прочитать существующую схему.

### Переход с БД скелета

1. Остановите запущенный Core и убедитесь, что `DB_URL` указывает на нужный файл. Миграции выполняйте одним процессом, до запуска сервиса.
2. Если в БД есть данные, создайте согласованную копию SQLite через Backup API, учитывающий WAL. Пример из `core/` использует текущий `DB_URL`, создаёт закрытый каталог backups и не перезаписывает существующую копию:

   ```bash
   python - <<'PY'
   import os
   import sqlite3
   from contextlib import closing
   from pathlib import Path
   from sqlalchemy.engine import make_url
   from app.core.config import settings

   url = make_url(settings.db_url)
   if url.drivername != "sqlite+aiosqlite" or not url.database or url.database == ":memory:":
       raise SystemExit("Нужна файловая SQLite-БД")
   source = Path(url.database).resolve()
   if not source.is_file():
       raise SystemExit("Файл БД отсутствует; для новой установки копия не требуется")
   backup = Path("backups/shade-before-task04.db")
   backup.parent.mkdir(mode=0o700, exist_ok=True)
   os.close(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
   with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db:
       with closing(sqlite3.connect(backup)) as copy:
           db.backup(copy)
   print("Копия сохранена:", backup)
   PY
   ```

3. Выполните `python -m alembic upgrade head`, затем `current` и `check`; после успеха запускайте Core обычной командой. На каждом старте повторный upgrade уже актуальной БД ничего не пересоздаёт.

Пустая БД получает все три таблицы. Существующая БД без версии принимается только при полном совпадении со схемой скелета: обе прежние таблицы, столбцы, типы, NULL/default, ключи и ограничения. Данные и идентификаторы сохраняются; таблицы не пересоздаются. Частичная или изменённая схема отклоняется, Core не начинает принимать запросы. При ошибке изменения схемы и версии откатываются транзакцией. Не обходите отказ через `stamp head`: нужно разобраться со структурой на копии.

`backups/` исключён из git и Docker-контекста. Старые миграции не редактировать после применения: изменение моделей сопровождается новой ревизией (`python -m alembic revision --autogenerate -m "Описание по-русски"`), её дифф проверяется вручную. Откат downgrade удаляет соответствующие таблицы с данными; резервная копия нужна для восстановления. Полный регламент резервирования и развёртывания на Pi остаётся TASK-08.

device_states хранит `entity_id` (TEXT, PK), `state`, `attributes_json` (по умолчанию `{}`), `last_changed` и `last_updated` (UTC). Это схема хранения: получение состояний HA и их запись реализуются в следующих задачах.

## Docker

После локальной установки и `python -m app.setup` выполните из `core/`:

```bash
docker build -t shade-core:local .
docker run --rm --env-file .env \
  -p 127.0.0.1:8000:8000 \
  --mount type=volume,src=shade-core-data,dst=/data \
  -e DB_URL=sqlite+aiosqlite:////data/shade.db \
  shade-core:local
```

Ключ передаётся при запуске через внешний `.env`; образ содержит только пустой шаблон. `.dockerignore` исключает рабочие `.env`, БД, модели, виртуальные окружения и тестовые артефакты. Образ не устанавливает зависимости тестов и LLM. Том сохраняет SQLite между запусками. Порт в примере доступен с локального компьютера.

В контейнере `127.0.0.1` указывает на сам контейнер. Для HA на другой машине укажите его адрес в локальной сети. Развёртывание на Pi, systemd и доступ клиентов по LAN остаются в TASK-08.

## Проверки

Из `core/` после активации окружения:

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
ruff check app tests
python -m pytest -q
```

Тесты самостоятельно изолируют настройки до импорта приложения: рабочий `.env` не читается, значения Core из окружения заменяются тестовыми. Каждый тест выполняется в отдельном каталоге; API-тест получает отдельную SQLite-БД, применяет настоящие миграции через lifespan приложения и освобождает движок на том же event loop. Тесты миграций отдельно проверяют пустую/старую БД, сохранение данных, повторный upgrade, несовместимые схемы, откат при сбое и CLI Alembic.

Home Assistant заменён на `httpx.MockTransport`: тестируются успешные ответы, отсутствие соединения и HTTP-ошибки. DNS и реальные TCP-соединения запрещены; попытка такого запроса провалит тест даже при перехваченном исключении. HA и LLM для pytest запускать не нужно, ключ вручную задавать не требуется.

Временные каталоги создаются в игнорируемом `core/.pytest_cache/` и удаляются после завершения pytest. Для новых API-тестов используйте fixtures `client`, `auth_headers` и `ha_mock` из [tests/conftest.py](tests/conftest.py); добавляйте необходимые маршруты и сценарии в mock. В этих fixtures используются общие настройки приложения, поэтому несколько TestClient одновременно в одном процессе не предусмотрены.

Результаты: [TASK-01](../docs/reports/task-01.md), [TASK-02](../docs/reports/task-02.md), [TASK-04](../docs/reports/task-04.md). Инференс, Android, реальные устройства HA и Raspberry Pi этими тестами не проверяются.
