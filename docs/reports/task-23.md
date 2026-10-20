# TASK-23 — локальный календарь

**Статус:** программная часть реализована, совместимость с настоящим Xandikos0.4.10 дополнительно проверена на синтетической коллекции; общий DoD открыт до пользовательского календаря/Pi/телефона. Реальная коллекция/credentials не запрашивались. Рабочие .env/БД/HA не менялись; напоминаний/режимов дома этот срез не создаёт.

## Допроверка20октября: настоящий Xandikos

[Протокол](task-23-xandikos.json) PASS: отдельный **Xandikos0.4.10**, настоящий Core/SQLite/HTTP на127.0.0.1, синтетические ICS через PUT. Сервер сам разворачивает RRULE/EXDATE/RDATE и перенос RECURRENCE-ID;9событий, DATE с исключающим end, floating в поясе Core и Europe/Berlin через смену DST24–26октября проверены по ожидаемому UTC. Повторный sync не меняет ID/revision, перенос сохраняет ID и увеличивает revision, STATUS:CANCELLED и DELETE дают разные cancelled/removed. Новый lifespan сохраняет ID/кэш; выключение Xandikos перед следующим lifespan даёт CALENDAR_UNAVAILABLE/stale с прежними записями. Приватный синтетический DESCRIPTION не возвращается; журнал HA-команд пустой.

Полный Core/Python3.14: **498 passed**, ruff app/tests/migrations/нового QA и Web build PASS; финальный повтор настоящего Xandikos/Core также PASS. Продуктовый код и маршруты не менялись. Начальный QA-прогон ожидал ISO без микросекунд, тогда как Core использует timespec=microseconds; ожидание исправлено, полный повтор PASS. Это не исправление ошибок CalDAV-продукта. Core clock фиксирован2026-10-20T03:00Z для воспроизводимости; системные часы не менялись. Реальны сервер и его RRULE-движок, но календарь **синтетический**, авторизация/TLS этого сервера не проверены (только loopback/no-auth), HA/native-модели/телефон/Pi отсутствуют. Нельзя переносить результат на все CalDAV-серверы.

Optional `core/requirements-caldav-check.txt` закрепляет только зависимости **внешнего QA-сервера**, не входит в requirements.txt/автоматический pytest и не устанавливается в Core/.venv. Подготовлено отдельным `pip --target core/.pytest_cache/task23-caldav-deps`,21готовый wheel: **6921897байт загрузки** плюс метаданные, **22418068байт содержимого**. Перед загрузкой проверены размер≤32MiB, распаковка≤128MiB, SHA-256 и резерв4GiB. Моделей/SDK/тяжёлых зависимостей не скачано; версии записаны в JSON. Это не предложение установить Xandikos на Pi без отдельной приёмки.

Воспроизведение с установленным отдельным target:

```bash
core/.venv/bin/python core/checks/check_calendar_xandikos.py \
  --dependencies core/.pytest_cache/task23-caldav-deps \
  --output docs/reports/task-23-xandikos-new.json
```

Существующий отчёт не перезаписывать. Установка fixture отдельно, только при измеренном запасе: из core выполнить `.venv/bin/python -m pip install --only-binary=:all: --no-cache-dir --no-compile --target .pytest_cache/task23-caldav-deps -r requirements-caldav-check.txt`; не ставить в runtime или системный Python. Обновлённые зависимости требуют нового протокола. Сам сценарий проверяет4GiB перед стартом, запускает сервер только на loopback, временную коллекцию/БД/логи держит в .pytest_cache и удаляет; finally завершает свой child, не чужие процессы. Это отдельный TCP-стенд, обычный pytest сохраняет сетевую изоляцию.

Основание запуска — [официальная документация Xandikos](https://www.xandikos.org/deployment/); использован строгий режим, без Avahi/iMIP/облачных функций. Конкретные CLI-параметры сверены с установленной0.4.10. Полный TASK-23 остаётся открытым по реальному календарю/Pi/клиенту.

## Реализация

Default CALENDAR_URL пустой. Явный URL коллекции по локальному IP, username/password только окружением/.env, TLS проверяется; proxy/redirect/автоповтор отключены. DNS/облачные URL не принимаются. Один ограниченный HTTPx-client/задача, закрытие до engine.dispose; CPU-парсинг вне loop и сеть вне DB. Новых библиотек/моделей/SDK не скачивали.

REPORT calendar-query/calendar-data/expand читает ограниченное окно (7прошедших/60будущих UTC-дней, запрос±48ч для DATE/floating), до1MiB/500экземпляров/5000XML-узлов. Сервер разворачивает повторы по [RFC4791 §9.6.5](https://www.rfc-editor.org/rfc/rfc4791.txt); Core не пишет собственный RRULE-движок. UTC/DATE/floating/IANA/DURATION, исключающий DTEND и DST обработаны явно; неоднозначное/несуществующее время не угадывается. Неразвёрнутые RRULE/RDATE/EXDATE/VTIMEZONE/частичный207 не становятся успешным снимком. Ориентир формата — [RFC5545](https://www.rfc-editor.org/rfc/rfc5545.txt). Это поддерживаемый срез протокола, не универсальная библиотека iCalendar.

Сохраняются только summary/location/время/DATE/статус/занятость/ревизия, хеш UID/recurrence; descriptions/attendees/alarms/attachments/rawICS не сохраняются и внешние ссылки не загружаются. Миграция0010: calendar_events/calendar_sync_state. ID сохраняется при переносе/изменении; неизменённый sync не меняет revision. CANCELLED без DTSTART отменяет известный экземпляр/серию; исчезнувшее из успешного окна — removed, без догадки о причине. Весь валидный snapshot применяется атомарно; ошибка сети/парсинга/commit оставляет прежний кэш со stale. Смена scope не раскрывает прежние данные; отключение/другой URL очищают старый scope при старте. До1000строк с очисткой вне окна/terminal.

Protected GET events/detail и POST sync, health.calendar, [API](../api-spec.md#47-локальный-календарь--программная-task-23). Web/Android: страницы50/фильтр неактивных/синхронизация/пояс Core/DATE без сдвига/stale/статусы; запросы/данные очищаются при смене подключения, экрана,401 и Android STOP. Sync привязан к показанной revision. Исправлен общий Web-заголовок разделов. Календарь не использует CalendarProvider и не требует доступа к календарю телефона.

## Проверки

- **375 pytest** Python3.14 и Python3.11 в существующем Docker/network none/RAM768MiB/tmpfs, ruff app/tests/migrations/checks.33 календарных проверки: форматы/UTC/IANA/DST/номинальные дни, развёрнутые экземпляры/перенос, отмена, частичный/ошибочный/большой ответ, credentials/local URL, стабильные IDs/ревизии, stale/clock/scope, SQL rollback, сериализация sync и отсутствие DB-lock во время сети. Общие миграционные проверки metadata/upgrade/downgrade прошли.
- Настоящий HTTP Core ↔ **синтетический REPORT-сервер**, две lifespan/та же SQLite:3события, stable ID/update, отмена2экземпляров серии, removed,500→старый кэш/stale, restart/error/auth PASS. [JSON](task-23-loopback.json), стенд core/checks/check_calendar.py. Сервер отдаёт заранее развёрнутые экземпляры: это **не** проверка настоящего CalDAV/RRULE-движка. Нативных моделей/реального HA/телефона нет.
- Web build/Node(calendar/processing/automations), Chromium синтетические routes: Core-пояс10:00, all-day19октября без сдвига,50+1пагинация/очистка прежней страницы, изменённое событие, stale,503 без повтора POST, отменённые,401 очистка,320px,0JS-ошибок/внешних запросов. Проверочный checks/calendar.js, снимок web/output/playwright/task23-calendar-mobile.png (игнорируется). Ошибки network console — ожидаемые503/401.
- **28 focused Android JUnit**, все Kotlin/Compose скомпилированы без Gradle;6новых тестов календаря проверяют формат/пояс/DATE, STOP/revision/страницы/поздний ответ, явный sync и настоящий Retrofit/Bearer/точный путь через loopback MockWebServer. Временные20.7MB удалены. Начальная ошибка слишком короткого синтетического ключа исправлена в тесте, production-валидация сохранена.
- На общем диске независимо от агента появился запас19GB, поэтому дополнительно выполнены **штатные assembleDebug/testDebugUnitTest/lintDebug полностью offline** (JDK17/Gradle8.10.2,worker1/heap768MiB/Kotlin in-process). **46 JVM,0 failures/errors/skipped; lint0ошибок/3warnings/1info; APK10519081байт, подписьv2 подтверждена.** [Хеш/метаданные](task-23-android.json). Сначала lint поймал SuspiciousIndentation в новом policy-блоке TASK-22: отступы/группировка исправлены, policy видна и принятому правилу, проверка повторена успешно; подавления lint нет. Предупреждения ObsoleteSdkInt/UnusedResources/MonochromeLauncherIcon, infoAutoboxingStateCreation. Это уже проверка APK/KSP/manifest merge, но не AVD/instrumented/телефон.

## Ресурсы и продолжение

Проверка Gradle запускается через android/checks/check_gradle_offline.py: старт≥6GiB диска/2GiB MemAvailable, stop собственной группы при<4GiB/<768MiB, никаких загрузок. Итог второй сборки: доступно15187353600→13194375168байт; это изменение **всего общего диска**, не объём наших файлов. Собственные восстановленные transforms/generated-jars/app-build около0.9GiB; кэш временно нужен следующим Android-задачам, после заключительной проверки удалить ненужные результаты. SDK/AVD/чужие данные не трогались, все GGUF по-прежнему удалены. Сейчас около13GB свободно; запас меняется другими процессами.

Исторически оставалась совместимость сервера;20октября Xandikos допроверен выше. Открыты: установленный пользовательский календарь/auth/TLS, Pi/4GB/длительная работа, AVD/instrumented/системный канал/телефон, полный Android→Core+GGUF конвейер и качество TASK-18. TASK-23/этапv0.5 не закрыты. Следующая доступная программная TASK-24 — напоминания и подтверждаемый режим встречи; stale/removed/cancelled не должны приводить к действию.
