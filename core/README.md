# Shade Core

Бэкенд Shade AI на FastAPI. Спецификация API: [`docs/api-spec.md`](../docs/api-spec.md), архитектура: [`docs/architecture.md`](../docs/architecture.md).

## Запуск

```bash
cd core
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполни SHADE_API_KEY и HA_TOKEN
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- Swagger UI: http://localhost:8000/docs
- Health: `curl http://localhost:8000/api/v1/health`

## Структура

```
core/
├── app/
│   ├── main.py              # FastAPI app factory
│   ├── api/
│   │   ├── deps.py          # аутентификация (Bearer API key)
│   │   └── v1/              # роутеры: health, notifications, ha
│   ├── core/config.py       # pydantic-settings (.env)
│   ├── db/                  # SQLAlchemy async + SQLite WAL, модели таблиц
│   ├── events/bus.py        # in-memory шина событий (asyncio)
│   └── services/
│       ├── ha_bridge/       # клиент Home Assistant REST API (httpx)
│       ├── llm/             # LLM Engine (интерфейс; llama.cpp — MVP v0.3)
│       ├── notification/    # конвейер обработки уведомлений
│       └── analytics/       # анализ привычек (MVP v0.4)
├── models/                  # GGUF-модели (в .gitignore; scripts/download_model.sh)
├── tests/
├── requirements.txt
├── requirements-llm.txt     # llama-cpp-python — ставить на RPi: pip install -r requirements-llm.txt
└── Dockerfile
```

## Тесты

```bash
pytest
```
