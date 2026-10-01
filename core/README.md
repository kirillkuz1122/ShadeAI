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
mkdir -p .pytest_cache
DB_URL=sqlite+aiosqlite:///./.pytest_cache/local-check.db \
HA_BASE_URL=http://127.0.0.1:1 HA_TOKEN= \
SHADE_API_KEY=shade-local-test-key-000000000001 \
timeout --signal=INT --kill-after=3s 30s python -m pytest -q
```

До TASK-02 тесты требуют явной подмены БД и адреса HA, как в примере. Тестовый ключ в команде не является рабочим секретом. Обычный pytest может использовать рабочие настройки.

Результаты TASK-01: [отчёт](../docs/reports/task-01.md). Инференс, Android, реальные устройства HA и Raspberry Pi этой задачей не проверяются.
