# Shade Web — дашборд Shade AI

React + Vite + TypeScript. Подключается к Shade Core API (`core/`), показывает состояние сервера и журнал уведомлений.

## Запуск

```bash
cd web
npm install
npm run dev        # http://localhost:5173 (прокси /api → localhost:8000)
```

Shade Core должен быть запущен (см. `core/README.md`).

## Настройка

1. Открой дашборд, вставь `SHADE_API_KEY` из `core/.env` в поле «Shade API ключ» → «Сохранить» (хранится в localStorage).
2. Данные обновляются автоматически каждые 10 секунд.

## Сборка

```bash
npm run build      # результат в web/dist/
```

Для продакшена на RPi: `npm run build`, затем раздавай `dist/` через nginx, проксируя `/api` на `127.0.0.1:8000`.
