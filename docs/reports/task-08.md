# TASK-08 — программная подготовка развёртывания

**Статус:** доступный программный срез реализован. Полная TASK-08 открыта:
Pi/boot/настоящий HA/физический свет/целевая RAM ещё не проверены. Никакие службы
на рабочий компьютер не устанавливались, рабочие.env/БД/HA не менялись.

## Изменения

- Core по явному WEB_DIST_PATH отдаёт отдельный собранный dist: same-origin Web+API,
  без Node/proxy в runtime. Default-off, прежние API/Bearer неизменны. В production
  docs/redoc с CDN отключены, OpenAPI JSON локальный. Startup manifest≤512объектов/
  32MiB, только index/shade.svg/assets, без symlink/исходников/секретов/листинга.
  CSP своим origin/no-referrer/nosniff, no-cache index/immutable hashedassets.
- deploy/: один Core/systemd-worker на SQLite, отдельный user/state/logs, read-only
  код/dist, local-IP cgroup policy, stop60с, MemoryHigh2560M/Max3072M на cgroup.
  Это предохранители, не измеренный расход Pi. Journald namespace отдельно:
  32MiB persistent/8MiB runtime/14дней, общий журнал не меняется.
- Backup service/timer04:00±15мин и stdlib scripts/sqlite_backup.py: readonly source/
  SQLite Backup API учитывает committed WAL, integrity_check/foreign_key_check/
  Alembic revision, закрытый standalone-файл600/каталог700, публикация без overwrite.
  Запас4GiB+размер перед копией и4GiB во время/потоковый SHA/deadline120с.
  Retention7 (настраиваемо1–30), только свой шаблон имён/после успешной проверки.
  Restore только в новый путь, существующие DB/WAL/SHM/journal/symlink не трогает.
  Нужна локальная POSIX ФС с hard-link/fsync.
- Инструкция ручной Pi-установки/backup/restore/проверок — [deploy](../../deploy/README.md);
  контракт/README/Core/Web/context синхронизированы. Секретов/новых зависимостей нет.

## Проверки

- **480Core на Python3.14 PASS**, полный **480Core на Python3.11/network none PASS**
  в существующем shade-core:task17-tests, без pull/новых образов. Ruff и Web build PASS.
-17новыхтестов: API/Bearer/404/405/CSP/cache, symlink/manifest/bounds, настоящий WAL
  с открытым writer и незакоммиченными изменениями, новый restore/целостность/схема/
  source без изменения, закрытые права/нет overwrite/retention/ошибка/disk/deadline.
  Финально52focused Access/dashboard/backup PASS, отдельно финальный backup3.11.
- Disk-budget unit-тестов синтетический (CI tmpfs128MiB), отказы задаются явно;
  настоящий guard4GiB используется в отдельном loopback. Исходный запуск CI дал
  477/3DISK_RESERVE — предохранитель правильно отклонил tmpfs. Не увеличивали его
  до гигабайт и не ослабляли runtime guard. Затем выявлен479/1SQLite-lock теста26:
  исправлен отдельно ae9e1f6, production AccessService не менялся.
- **Настоящие процессы Uvicorn/HTTP→SQLite/Web**: create→live WAL backup→SIGTERM/
  новыйпроцесс/тажеБД→новыйrestore/третийпроцесс — запись сохранена, ревизия
  0013_access_grants. [JSON](task-08-loopback.json). LLM/STT выключены; HA намеренно
  недоступный loopback, HA-команд нет.
- **Chromium/production dist**: авторизация/список/детали/Escape/320px, без JS-ошибок,
  внешних запросов или нарушений CSP. Использованы уже существующие CLI/Chromium,
  npx offline. Свои процессы Core/Chromium закрыты, temporaryDB удалены.
- systemd-analyze verify: исходный unit ожидаемо сообщил отсутствие /opt/.../python
  на компьютере. Тестовые копии с заменой только ExecStart binary на существующий
  /usr/bin/python3 проходят verify. Это синтаксис, **не запуск systemd/boot/проверка
  cgroup-BPF/memory/journald на Pi**. Шаблоны в /etc не устанавливались.

Воспроизведение: Core README и check_deployment.py --browser --output <новыйjson>.
Без браузерного флага доступна HTTP/restart/backup/restore часть. Вывод без текстов/
ключей/путей БД; fixture полностью синтетический. Копия SQLite содержит приватные
данные, её не публиковать; сохранение ключей/.env/моделей отдельно локально.

## Что остаётся

Установка на Pi с заранее подготовленными ARM-зависимостями, boot, cgroup/BPF,
реальный LAN/Android/HA/свет, восстановление на целевой ФС, измерение RAM/диска/
охлаждения. Backup на том же диске не защищает от отказа носителя — нужна проверенная
копия на второй локальный носитель. Нельзя объявлять совместную LLM/STT/HA работу
на4GB доказанной по MemoryMax.17задач и аппаратный чекбокс08 остаются открыты.
Следующая доступная программная работа — TASK-27: bounded сбор метрик и протокол
аппаратной/14дневной приёмки, без имитации пройденных14дней.

Основания реализации: [FastAPI StaticFiles](https://fastapi.tiangolo.com/tutorial/static-files/),
[SQLite Backup API Python3.11](https://docs.python.org/3.11/library/sqlite3.html#sqlite3.Connection.backup),
[systemd resource control](https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html).
