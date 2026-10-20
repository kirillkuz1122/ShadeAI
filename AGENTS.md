# AGENTS.md — правила работы с проектом Shade AI

Этот файл — «точка входа» для AI-агентов (и людей) в новой сессии. Прочитай его целиком перед тем, как что-то менять.

---

## 1. Что это за проект

**Shade AI** — персональный автономный AI-ассистент и «мозг умного дома», полностью локальный (Zero-Cloud):

- **Железо:** Raspberry Pi 5 (4GB RAM), Home Assistant, WirenBoard, Zigbee.
- **Идея:** Android-клиент перехватывает уведомления и голос → локальная LLM на RPi извлекает интенты → аналитический движок изучает привычки → команды уходят в Home Assistant. Ни один байт не уходит в облако.
- **Автор:** Кузмичев Кирилл, соло-разработчик. Проект готовится к конкурсу «Большие вызовы».

**Ключевое ограничение при написании любого кода:** целевая машина — 4GB RAM, всё должно работать локально. Никаких внешних облачных API-вызовов в рантайме.

---

## 2. Где что лежит (карта проекта)

```
ShadeAI/                          ← корень репозитория
├── AGENTS.md                     ← ты здесь
├── README.md                     ← витрина проекта (badges, архитектура, быстрый старт)
├── docs/                         ← ВСЯ документация (главное чтение)
│   ├── architecture.md           ← архитектура: компоненты, БД, потоки данных, RAM-бюджет
│   ├── api-spec.md               ← контракт REST API (ЭНДПОИНТЫ МЕНЯТЬ ТОЛЬКО ЧЕРЕЗ ЭТОТ ФАЙЛ)
│   ├── mvp.md                    ← задачи TASK-01–27, статусы, зависимости, DoD и roadmap
│   ├── project-context.md        ← память проекта: состояние, решения, проверки, следующий шаг
│   ├── reports/                  ← отчёты о выполнении задач и проверках
│   ├── tech-stack.md             ← стек технологий и обоснования
│   └── brand.md                  ← брендбук: палитра, тон текста
├── core/                         ← бэкенд «Shade Core» (Python 3.11+ / FastAPI)
│   ├── app/api/v1/               ← роутеры: health, notifications, ha, devices, events, telemetry
│   ├── app/core/config.py        ← настройки из .env (pydantic-settings)
│   ├── app/db/                   ← SQLAlchemy async + SQLite (WAL)
│   ├── migrations/               ← Alembic: начальная схема и последующие ревизии
│   ├── app/events/bus.py         ← шина событий (asyncio)
│   ├── app/services/             ← ha_bridge, llm, notification, telemetry, analytics
│   ├── tests/                    ← pytest
│   ├── .venv/                    ← виртуальное окружение (в git НЕ входит)
│   └── models/                   ← GGUF-модели (в git НЕ входят; scripts/download_model.sh)
├── android/                      ← клиент (Kotlin + Jetpack Compose)
│   └── app/src/main/java/com/shadeai/app/
│       ├── core/network/         ← Retrofit + kotlinx-serialization
│       ├── core/config/          ← адрес сервера, allowlist приложений
│       ├── data/db/              ← Room-буфер уведомлений
│       ├── service/              ← NotificationListenerService
│       └── ui/                   ← Compose-экраны, тема из brand.md
├── web/                          ← дашборд (React 19 + Vite + TypeScript)
│   └── src/api/client.ts         ← типизированный API-клиент
├── scripts/download_model.sh     ← скачивание LLM-моделей
├── index.html + visitka/         ← сайт-визитка (GitHub Pages, не трогать без нужды)
└── LICENSE                       ← MIT
```

## 3. Как войти в проект в новой сессии (порядок чтения)

1. **Этот файл** (AGENTS.md).
2. [docs/project-context.md](docs/project-context.md) — состояние последней сессии, принятые решения, известные проблемы и следующий шаг.
3. `README.md` — общая картина и быстрый старт.
4. [docs/mvp.md](docs/mvp.md) — единый список задач, зависимости и критерии готовности.
5. `docs/architecture.md` — если нужно писать код: компоненты, схема БД, потоки.
6. `docs/api-spec.md` — если трогаешь API (бэкенд / веб / Android-клиент).
7. `git status --short` и `git log --oneline -20` — незакоммиченные изменения и свежая история; не перезаписывать чужие правки.
8. Проверить, что всё живо:
   ```bash
   cd core && .venv/bin/python -m pytest -q   # тесты бэкенда
   cd ../web && npm run build                 # сборка дашборда
   ```

Обычный pytest теперь изолирован fixtures: рабочий `.env` не читается, каждый API-тест получает отдельную SQLite-БД, HA подменяется mock-транспортом, DNS и реальные TCP-соединения запрещены. Временные данные лежат в игнорируемом `core/.pytest_cache/` и удаляются после запуска. Подробности — [инструкция Core](core/README.md) и [отчёт TASK-02](docs/reports/task-02.md).

**Статус на 2026-10-20:** 17 задач открыты, этапы целиком не приняты. Программные19–26 реализованы; owner26/voice-focus/OS19/OS21 проверены, отдельные отчёты в docs/reports. Программные08(deploy/Web/WAL backup) и27(bounded probe/runbook) проверены на компьютере. Последняя допроверка24: AOSP35/read-only, настоящий reboot→alarm/уведомление без Activity и первый alarm в forced deep IDLE без постоянного whitelist PASS; API синтетический, не Core/HA/CalDAV. Doze на AVD явно включён QA, не естественный режим телефона. [Отчёт24](docs/reports/task-24.md), [OS boot/idle](docs/reports/task-24-recovery-os.json), [offline/retry](docs/reports/task-24-offline-os.json) без Activity также PASS на синтетическом API. Повторно498Core3.14/ruff/Webbuild PASS. Native речь/Pi/телефон/HA/CalDAV/длительность открыты;18:70%/max4.137с. Моделей нет, не скачивать; диск общий~27GiB. **После сводки Кирилл поручил «делай дальше»: работа возобновлена. Настоящий Xandikos0.4.10/Core23 на синтетической коллекции PASS; [протокол](docs/reports/task-23-xandikos.json). Физические критерии открыты.** [Ночь20](docs/reports/night-2026-10-20.md), [память](docs/project-context.md), [задачи](docs/mvp.md).

---

## 4. Правила для агентов

### Язык и стиль
- Всегда отвечай пользователю на русском, даже если запрос на английском.
- Вся документация и коммиты — **на русском** (как в остальном проекте).
- В коде комментарии — только когда без них не понять замысел.

### Проектная память, задачи и продолжение в новой сессии

- По просьбе пользователя все проектные задачи, заметки, решения, отчёты и контекст для будущих сессий хранить **в репозитории**, в `docs/`. Планы и память проекта не должны зависеть от `/tmp`, личной памяти агента или истории чата.
- Единый список задач — [docs/mvp.md](docs/mvp.md). При обсуждении и реализации использовать идентификаторы `TASK-XX`; не создавать второй несогласованный список. Завершение отмечать только после выполнения критериев и записи проверок.
- Память проекта и передача работы — [docs/project-context.md](docs/project-context.md). В конце содержательной работы обновлять: что изменено, какая задача в работе/закрыта, что проверено, ограничения и следующий шаг. Не записывать секреты, личные сообщения и содержимое рабочего `.env`.
- В `AGENTS.md` поддерживать ссылки на важные проектные документы, порядок чтения и устойчивые правила. Подробные результаты сессии и карточки задач хранить в документах выше, чтобы не дублировать их полностью здесь.
- Временные вспомогательные файлы создавать в подходящем каталоге проекта и удалять после использования. Тестовые БД и сборки держать в уже игнорируемых каталогах; они не являются проектной памятью и не должны попадать в git.
- Перед продолжением сверять заметки с текущим кодом и `git status`: снимок прошлой сессии может устареть. Различать **ТЗ**, **код уже написан** и **поведение проверено**; не объявлять весь компонент готовым по существованию файлов или успешной сборке.

### Диск и совместная работа

- Диск общий с параллельной работой Claude, свободного места мало. Перед загрузкой/тяжёлой сборкой проверять `df -h .` и объём результата; после работы удалять только свои ненужные артефакты. Без новых моделей и тяжёлых зависимостей при текущем дефиците места.
- Загрузчик GGUF сохраняет минимум 4 GiB свободными и проверяет место перед сетью и каждым блоком записи; уже готовая модель переиспользуется без загрузки. Этот резерв не гарантирует место при одновременной записи другими процессами.
- При малом запасе Android-сборки не запускать. `android/checks/check_gradle_offline.py`: offline/no-daemon/1worker, старт≥6GiB диска/2GiB RAM, stop<4GiB/768MiB. Guard AVD: старт≥6GiB/3GiB RAM, read-only/noaudio, stop<4GiB/1GiB. Android26/voice-focus:82JVM/APK/lint PASS; после финальных проверок удалено901836800байт только собственных regenerable caches/intermediates/tmp/generated. LatestAPK/метаданные/SDK/JDK/AVD сохранены.
- Не делать общую очистку Docker/кэшей, не удалять чужие контейнеры, БД, Android SDK/AVD или файлы Claude. Из-за падения остатка до 168 MB удалены все три собственные GGUF после сохранения измерений; в models сейчас моделей нет. Заново не скачивать их без достаточного измеренного запаса.

### Правила коммитов

По прямому указанию пользователя после каждой завершённой задачи делать отдельный коммит и push в текущую рабочую ветку. Не запрашивать повторное разрешение на эти действия. Перед отправкой выполнять проверки, обновлять задачи/контекст и проверять состав staged-файлов; секреты и артефакты не отправлять.

Каждый коммит обязан быть понятен без открытия диффа. Формат сообщения:

```
<тип>(<область>): краткое описание по-русски (до ~60 символов)

Что сделано:
- изменения по файлам/модулям, по пунктам

Почему так:
- обоснование неочевидных решений (опционально)

Проверено: <pytest / npm run build / что именно проверено руками>
```

- **Типы:** `feat` — новое, `fix` — баг, `refactor` — без изменения поведения,
  `docs` — документация, `chore` — инфраструктура/скрипты/конфиги.
- **Области:** `core`, `web`, `android`, `docs`, `scripts`; если затронуто
  несколько — перечислить через запятую или опустить.
- **Тело обязательно**, если изменений больше одного тривиального файла:
  перечислять, что именно изменилось («обновил файлы» — не описание).
- **Один коммит = одна логическая задача.** Файлы по разным задачам —
  разбить на несколько коммитов.
- Изменения API → в том же коммите обновлён `docs/api-spec.md`
  (и это указано в теле коммита).
- Эмодзи-префикс в начале заголовка — по вкусу, как в истории репозитория.
- Force-push: только `--force-with-lease` и только пока проект соло-веточный.

### Технические соглашения
- **Python:** 3.11+, async/await, типизация; линтер `ruff` (`cd core && .venv/bin/ruff check app tests`); зависимости приложения добавлять в `core/requirements.txt`, тестов и разработки — в `core/requirements-dev.txt` (LLM — только в `requirements-llm.txt`). Установка и разбор ошибок — [core/README.md](core/README.md).
- **Настройка Core:** `cd core && .venv/bin/python -m app.setup` создаёт локальный `.env` с ключом и правами 600. Существующий корректный ключ сохраняется. Используется только `SHADE_API_KEY`, без него сервер не запускается; переменная окружения имеет приоритет над `.env`. Не включать рабочие секреты в Docker-образ.
- **Тесты Core:** для API использовать fixtures `client`, `auth_headers`, `ha_mock` из `core/tests/conftest.py`. Не подключать тесты к рабочей БД/HA и не отключать сетевую защиту; новые HA-маршруты добавлять в mock. Fixtures подменяют общие настройки: не открывать одновременно несколько TestClient в одном процессе.
- **БД и миграции:** менять схему новой ревизией в core/migrations/ и синхронно ORM-моделью. Применённые ревизии не редактировать, create_all/stamp head вместо миграций не использовать. Core применяет upgrade head до приёма запросов; CLI использует тот же DB_URL/.env. При первом переходе старой БД остановить Core и сделать копию по [core/README.md](core/README.md#миграции-бд). Использовать общую create_db_engine: она задаёт WAL, foreign_keys и транзакционный DDL. Проверка линтером: `cd core && .venv/bin/ruff check app tests migrations`.
- **API:** любое изменение эндпоинтов синхронизировать с `docs/api-spec.md` в том же коммите. Аутентификация — `Authorization: Bearer <SHADE_API_KEY>`.
- **Android:** Kotlin, Jetpack Compose, Room, Retrofit; палитра только из `docs/brand.md` (#423E3B, #FF2E00, #FEA82F, #FFFECB). Состояние подключения — ConnectionViewModel/StateFlow; использовать общий ShadeApi.create с явным снимком адреса/ключа. Health без Bearer, защищённые запросы с Bearer; redirect/proxy/автоповтор выключены. Ключ — только через ServerPrefs/Android Keystore, не хранить в SavedState/логах/открытом prefs, не переносить на другой URL без нового ввода. Не включать backup или HTTP глобально. [Инструкция и тесты](android/README.md#настройки-и-проверка-подключения-task-09).
- **Источники Android (TASK-10):** явный выбор из NotificationSources (по умолчанию пусто), не расширять на банки/мессенджеры без пересмотра политики. Listener пишет/отправляет только через общий NotificationCapture; проверять доступ/выбор/текст до Room и перед HTTP, сохранять порядок выбора/отправки через Mutex. Не запрашивать доступ к скрытому содержимому Android 15; заглушки ОС пропускать. UUID и версии реализованы в программной TASK-11; фоновая надёжность — TASK-12. Optional checks/publisher — только синтетический эмуляторный стенд; не зависимость приложения. [Поведение и воспроизведение](android/README.md#доступ-к-уведомлениям-и-источники-task-10).
- **Буфер Android (TASK-11):** Room v3 и экспортированные схемы v1/v2/v3 в android/app/schemas, миграции без destructive fallback. Новые UUID/payload неизменяемы на повторах, изменение текста — новая версия; исходный Android key не сохранять, только хеш. Старые v1 отправляются с event_id=null ради совместимости отпечатка. Запись не должна ждать сеть, Mutex-порядок delivery→state; перед отправкой перечитать строку по ID. Сохранять лимиты/очистку и отмену сессии listener; фоновая доставка реализована в TASK-12. [Правила/проверки](android/README.md#форматы-идентичность-и-локальный-буфер-task-11).
- **Доставка Android (TASK-12):** буфер отправлять только из NotificationDeliveryWorker через общий capture, до 100 строк/45 с за запуск. Уникальная цепочка WorkManager и recovery 15 мин; отсутствие INTERNET/VALIDATED не блокирует LAN, при полном отсутствии сетей HTTP не запускать. Backoff Core/связи 30 с→6 ч и 401/config-пауза хранятся в delivery_control; не сбрасывать их на новые события/restart/сетевые callbacks. Новый ServerPrefs revision (случайный, без ключа) при сохранении/удалении настроек снимает паузу; изменение настроек упорядочено deliveryMutex. 400/409/413/422 — REJECTED отдельной строки, прочие ошибки классифицировать; receipt и gate писать атомарно, ошибку Room передавать worker для backoff. WorkManager Data не содержит payload/секретов. Проверки/ограничения/синтетический прокси — [Android README](android/README.md#надёжная-доставка-и-повторы-task-12), [отчёт](docs/reports/task-12.md). Doze/OEM/телефон — TASK-13, force-stop требует нового запуска приложения.
- **Журнал Android (программная TASK-13):** NotificationJournal читает строки/счётчики/gate одной транзакцией, InvalidationTracker совместим с Room 2.6. Страницы 50+1 с границей ID, новые записи не сдвигают старую страницу; смена фильтра/ошибка очищает прежние данные. JournalRoute наблюдает только в STARTED, при выходе/STOP отменяет подписку и очищает текст из UI-state. Перед чтением общий capture.refresh, не обходить политику и не сбрасывать gate чтением. В SavedState только маршрут/ID карточки, без payload; неизвестный lastError переводить безопасным fallback, не выводить raw. Журнал — локальный буфер, не архив; удаление на Android не удаляет Core. [Инструкция/стенд](android/README.md#журнал-уведомлений-программная-task-13), [отчёт](docs/reports/task-13.md). Сначала Gradle, затем UI-стенд: тестовый раннер может очистить debug-приложение; только одноразовый AVD.
- **Web:** React + TypeScript, стили через CSS-переменные бренд-палитры, `npm run build` должен проходить без ошибок TS. Health и защищённые списки обновлять независимо; запросы через useResource/AbortSignal, ключ явно передавать в API-методы. Смена ключа очищает данные, ответы прежней страницы/фильтра не применять. Не подключать внешние шрифты/CDN. Поведение и браузерная проверка — [Web README](web/README.md), [отчёт TASK-07](docs/reports/task-07.md).
- **Данные:** в БД/логи не писать банковские коды и личные переписки без необходимости — см. политику приватности в `docs/architecture.md` §5.1.
- **Уведомления (TASK-05):** вход только через сервис приёма с проверкой политики до INSERT. Не возвращать raw input в ошибках и не логировать SQL-параметры/тексты. POST не вызывает process_notification/шину сырых данных. UUID event_id отправителя стабилен на повторах; без него действует отпечаток нормализованных полей. Правила допуска, срока хранения и очистки — [Core README](core/README.md#уведомления-task-05), контракт — [api-spec.md](docs/api-spec.md). Изменение правил может удалить старые записи при следующем старте; сначала сделать резервную копию.

- **HA и аудит (TASK-06):** пользоваться общим HAClient lifespan через get_ha_client и execute_command, не создавать HTTP-клиент на запрос. Pending-журнал фиксировать до сети, не удерживать транзакцию во время ожидания HA; при сбое аудита до отправки команду не посылать. Автоповтора нет: timeout/unknown мог наступить после выполнения. Success означает принятие HA, наблюдение состояния отдельно; pending после рестарта — interrupted/unknown без повторной отправки. В журнал/логи не писать params, ответы HA, тексты и токены. Старый ha/action сохранять до проверенного перехода клиентов. Лимиты/retention/логи — [Core README](core/README.md#home-assistant-журнал-и-логи-task-06); схема журнала — ревизия 0004. Телеметрия/выбранный DeviceState добавлены программной TASK-14 отдельным сборщиком; REST команд/устройств сохраняет своё поведение.

- **Телеметрия HA (программная TASK-14):** явный HA_TELEMETRY_ENTITIES, по умолчанию [], до 100 числовых sensor/binary_sensor. Не сохранять произвольные HA-атрибуты; snapshot и live различать, sync/разрыв покрывать gap без восстановления переходов. Checkpoint только baseline/pong; снимок/кэш/закрытие gap атомарны. Один collector на БД, останавливать до engine.dispose. Backoff относится только к соединению сбора, команды не повторять. Короткие TelemetryStore gap/checkpoint/write завершают commit/rollback при отмене до возврата stop; не закрывать engine раньше и не распространять shield на сеть. Лимиты/очистка, контракт и воспроизводимый loopback — [Core README](core/README.md#телеметрия-ha-task-14), [API](docs/api-spec.md#426-телеметрия-ha--task-14), [отчёт](docs/reports/task-14.md). Обычные pytest по-прежнему без TCP; реальный WS-стенд запускать отдельно, только с синтетическими данными.

- **Локальный движок (TASK-16):** один LocalLLMEngine/stdio child, CPU и SHA-256 вне HTTP event loop. Default LLM_ENABLED=false; только заранее подготовленный локальный GGUF и optional requirements-llm.txt, runtime без скачивания. RLIMIT_AS — виртуальная память child, не общий RSS-бюджет Pi. Timeout/cancel завершает/reap процесс, следующая загрузка явная; параллельный вызов сразу LLM_BUSY. Не наследовать секреты/proxy в child, native stdout/stderr не логировать; fixed LLM_* наружу. Worker останавливается до модели. Health ready означает только загруженный движок. [Параметры/стенды](core/README.md#локальный-движок-llm-программная-task-16), [отчёт](docs/reports/task-16.md). GGUF/part/lock не коммитить, компьютер не заменяет Pi.

- **Очередь Core (TASK-15):** один NotificationWorker/процесс на БД, Queue только ID (64, максимум 256), durable processing_* и atomic claim/finish, без DB-транзакции во время handler. POST receipt stored/duplicate/skipped сохранять, точный статус — GET processing_status. Default disabled; diagnostic без анализа/категории/LLM, только явно. Handler чистый async/cancellable, без HA; CPU в TASK-16 — вне event loop. После аварии processing→pending, attempts сохранять; terminal failed не переигрывать. При ошибке finish повторять commit, не вычисление. Stop до engine.dispose, повторный stop безопасен. [Core README](core/README.md#очередь-обработки-уведомлений-task-15), [API](docs/api-spec.md#414-состояния-обработки--task-15), [отчёт](docs/reports/task-15.md).

- **Профили присутствия (TASK-20):** ANALYTICS_PRESENCE_ENTITY только явно выбранный binary_sensor присутствия из HA_TELEMETRY_ENTITIES, default None. Snapshot/gaps/unknown/неверные часы/дребезг не являются событиями. Полные локальные дни, ограничения 10000/1000, CPU вне loop, атомарные профили/снимок и stop до dispose. confidence — эвристический score, не вероятность; telemetry_stale/старый config учитывать отдельно, профиль не разрешает HA-действие. [Контракт](docs/api-spec.md#43-аналитика--программная-task-20), [отчёт](docs/reports/task-20.md).

- **Напоминания Android (TASK-24):** отдельный default-off opt-in, connection revision + calendar source_id; не расширять HintPrefs. Exact-only Special Access/POST_NOTIFICATIONS, WorkManager15мин только сверяет расписание. Receiver коротко валидирует Core, без сети/при stale/cancel/expiry не показывает; retry только grace5мин. В prefs/Data только IDs/сроки/receipt, без текста/URL/ключа. Повтор event_id+due_at; notify/receipt не атомарны. Отмена только своих alarms/notifications. Force-stop требует открытия; Doze/частота allow-while-idle не гарантируют срок. Режим встречи — explicit policy/scope/targets, disable доступен stale, unknown ack checked=true обязателен и команд не посылает. [Инструкция](android/README.md#напоминания-календаря-и-режим-встречи--task-24), [отчёт](docs/reports/task-24.md).

- **Голос (TASK-25):** отдельные VOICE_ENABLED=false/VOICE_TARGETS={} и pinned local Vosk bundle, никаких загрузок/Model(lang)/SpeechRecognizer. WAV PCM16/16kHz/mono0.25–10сек≤320044байт, auth/single-flight до body, CPU/native вне loop. Child без ключей/proxy/Python-сети, память/CPU/timeout/kill/reap; Pi4GB aggregate ещё не проверен. Строгие alias→light on/off, не LLM-NLU; preview ничего не выполняет. Confirm strict scope+true, durable dispatching до общего аудита/HA, timeout/restart без повтора. AudioRecord только RESUMED+window focus, потеря фокуса/PAUSE/смена Core отменяют и очищают, без audio/text в SavedState/WorkManager/файлах/БД. [Инструкция](android/README.md#голосовая-команда--task-25), [отчёт](docs/reports/task-25.md).

- **Доступ26:** default-off и отдельный keypad token, не владелец; только локальный Shade Keypad→Core→HA unlock, не vendor PIN slots. Owner проверяет доставку/цель/1–15мин/два strict согласия. HMAC/дедупликация/rate/durable consume до аудита/HA, timeout/restart без повтора. Unknown блокирует новую выдачу до ручного checked/revoke. PIN только первый ответ/Android RAM; история без него, FLAG_SECURE до сети. Очищать на PAUSE **и потере фокуса окна**: Overview может оставлять RESUMED. Скрытие не означает отзыв и не запирает дверь. [API](docs/api-spec.md#48-временный-доступ-shade-keypad--core-основа-task-26), [отчёт](docs/reports/task-26.md).

### Запрещено
- Коммитить: `.venv/`, `node_modules/`, `*.gguf`, `shade.db`, `.env`, сборочные папки Android (всё уже в `.gitignore` — не удалять оттуда строки).
- Хардкодить секреты (токены HA, API-ключи) в коде — только через `.env` / `core/.env.example` (примеры, не реальные ключи).
- Ломать совместимость API без обновления `docs/api-spec.md` и Android/web клиентов.
- Устанавливать тяжёлые зависимости «на всякий случай» — RAM на RPi 5 ограничена.

### Проверки перед завершением задачи
1. `cd core && .venv/bin/python -m pytest -q` — тесты зелёные.
2. Изменён API? → обновлён `docs/api-spec.md`.
3. Изменён README/docs? → нет битых ссылок на файлы.
4. `git status` — в коммит не попали артефакты сборки.

---

## 5. Известные ловушки

- Рабочая директория проекта: `~/programing/ShadeAI` (проверяй `pwd`, не guessing путей).
- `uvicorn` запускать из папки `core/` (модуль `app.main:app`).
- React-дашборд в dev-режиме проксирует `/api` на `localhost:8000` (см. `web/vite.config.ts`); без запущенного Shade Core будет «Нет связи».
- Для Android нужны JDK 17 и Android SDK Platform 35/Build Tools 34.0.0. Использовать Gradle Wrapper 8.10.2 или Android Studio; системная Java 26 не подходит для этой версии Gradle. Локальные инструменты TASK-03 находятся в `android/.gradle/`; команда — [android/README.md](android/README.md). Не коммитить SDK, кэш, APK и local.properties.
- Android HTTP разрешён только для адресов из [Network Security Config](android/app/src/main/res/xml/network_security_config.xml). Для другого IP добавить точный адрес и пересобрать APK либо использовать HTTPS с доверенным сертификатом. Bearer и настройка ключа реализованы в TASK-09; разрешение доступа к уведомлениям выдаётся через системные настройки с экрана TASK-10, источники по умолчанию выключены. Проверка эмулятора не заменяет аппаратную приёмку телефона.
- В `docs/mvp.md` чекбоксы DoD — план, не факт выполнения; не ставить `[x]`, пока критерий реально не проверен.

**Извлечение TASK-17:** NOTIFICATION_PROCESSOR=llm включается только вместе с LLM_ENABLED. До claim ждать ready, pending/attempts не расходовать. Schema v1/описательный intent/action_authorized=false; 3 фиксированные dev-пары, source только буквальные цитаты; время от timestamp + NOTIFICATION_TIMEZONE, не от дня worker. Не угадывать неоднозначное время, не выполнять HA из результата. Ошибки только fixed LLM_*, сериализацию невалидного BaseModel не логировать. При оценке фиксировать hash всего prompt+examples и отдельного набора, после просмотра eval не объявлять повтор на том же наборе независимой проверкой. [Контракт](docs/api-spec.md#415-результат-извлечения--программная-task-17), [инструкция](core/README.md#извлечение-уведомлений-программная-task-17).

**Предложения TASK-21:** только актуальный профиль≥0.75 и явная цель из AUTOMATION_ALLOWED_LIGHTS (default[]). Смена условий/политики требует нового решения; rejected/disabled sticky, disable допускает старую версию. В TASK-21 enabled означает согласие; TASK-22 добавляет отдельный выключенный по умолчанию исполнитель и явный policy-v1/scope. Fresh live off→on+checkpoint/no-gap+канонический LLM delivery даёт общую подсказку, без команды. Feed_id/cursor каждого клиента, TTL7дней/cooldown1час; Android отдельный opt-in/permission/WorkManager15мин, cursor+NotificationManager не атомарны, OS/Doze ещё не проверены. Короткие фазы записи telemetry/analytics/suggestions используют sqlite_immediate до чтения; никаких сети/CPU внутри. [Контракт](docs/api-spec.md), [отчёт](docs/reports/task-21.md).

**Исполнение TASK-22:** default false, два разных выбранных binary_sensor: личное и общее присутствие всех жильцов; реальную независимость/покрытие проверить на железе. Policy-v1/approval_scope клиента обязателен при enabled, смена режима/источников/задержки/cooldown снимает прежнее согласие. Fresh live2перехода/окно/checkpoint/no-gap, pending до отмены, повторная проверка перед dispatching, общий audit до HTTP. После dispatching отмена409, неизвестную команду не повторять. Restart pending→cancelled/dispatching→unknown. Сеть вне DB, cooldown общий для цели, bounded1000run/20pending. Web-журнал/cancel и [API](docs/api-spec.md), [отчёт](docs/reports/task-22.md); рабочее исполнение не включалось.

**Календарь TASK-23:** CALENDAR_URL defaultNone, только явная локальная IP-коллекция, credentials скрыты. REPORT/expand по RFC4791; без собственного RRULE/новых библиотек, не принимать неразвёрнутый/частичный snapshot. Ограничения1MiB/500instance/1000cache, parser CPU вне loop, writer после сети атомарный. UTC/DATE/floating/IANA/DST без догадки, revision/ID стабильны; cancelled/removed различать, при сбое старый кэш stale. descriptions/attendees/attachments не хранить/не загружать. Никаких напоминаний/HA в23; scope-смена/отключение очищает старый кэш. [API](docs/api-spec.md#47-локальный-календарь--программная-task-23), [отчёт](docs/reports/task-23.md). Реальный CalDAV пока не принят.

**Core-основа TASK-24 (ещё не полный результат):** reminders отдельно от delivery hints, defaultfalse; rmd IDs из CalendarEvent/revision/lead, validate перед показом, grace300с/50upcoming/24ч, без текста. source_id не переносит старый opt-in. Meeting defaultfalse/allowed switch[]; явный event revision/scope/targets, общий lease/пересечения, started-target не сбрасывать ack/тем же согласием. Snapshot fresh/confirmed/busy/non-DATE≤8ч; active при stale только до сохранённого конца. Restore лишь наблюдаемое собственное off→on по context hash/timestamps; внешнее on/ручные изменения не выключать. In-flight→unknown без повтора; ack checked=true только после ручного осмотра, без команды. User_id/Calendar-текст не писать в mode журнал. Android/Web-клиентское управление реализовано; аппаратная приёмка открыта. [API](docs/api-spec.md#471-расписание-напоминаний--core-основа-task-24), [отчёт](docs/reports/task-24.md).
