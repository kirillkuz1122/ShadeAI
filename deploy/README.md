# Локальное развёртывание — программная часть TASK-08

Шаблоны не устанавливались на рабочий компьютер. Boot/systemd на Pi, реальный HA,
телефон, суммарная RAM и отключённый интернет ещё требуют аппаратной приёмки.
Проверки на компьютере — [TASK-08](../docs/reports/task-08.md).

## Подготовка целевой установки

Нужны 64-битная ОС с systemd/journald namespaces (systemd≥245), Python≥3.11,
готовое окружение `core/.venv` **для архитектуры Pi**, локально собранный `web/dist`.
Сборку/зависимости подготовить заранее; во время работы ничего не скачивается.
Не переносить x86-venv с компьютера на ARM. Установка библиотек/моделей и сетевые
правила самого HA находятся вне этих шаблонов. Новые модели здесь не требуются:
LLM/STT/автоматика/доступ остаются выключенными, пока явно не настроены и проверены.

Разместить проверенный код в `/opt/shadeai`: `core/app`, `core/migrations`,
`core/alembic.ini`, `core/.env.example`, подготовленная `core/.venv`, `web/dist`,
`scripts/sqlite_backup.py`, `deploy`. Каталог и dist принадлежат администратору,
service-user не должен менять код/dist. Не класть туда рабочие `.env`, БД,
исходные Android/Node-кэши. `WEB_DIST_PATH` принимает только index.html, shade.svg
и ограниченный assets; symlink/исходники/секреты/лишние каталоги отклоняются.
Лимит512объектов/32MiB, список файлов фиксируется при старте. Обновлять dist
при остановленном Core и затем запускать заново, сохраняя предыдущую версию.

Следующие команды — **ручная установка на Pi**, не результат её выполнения:

```bash
sudo useradd --system --user-group --home-dir /var/lib/shadeai --shell /usr/sbin/nologin shadeai
sudo install -d -o shadeai -g shadeai -m 700 /var/lib/shadeai /var/lib/shadeai-backups /var/log/shadeai
sudo -u shadeai env PYTHONPATH=/opt/shadeai/core /opt/shadeai/core/.venv/bin/python -m app.setup --env-file /var/lib/shadeai/.env
sudoedit /var/lib/shadeai/.env
```

Если пользователь уже существует, повторно создавать его не нужно. В закрытом
`.env` настроить локальный HA/его токен, остальные функции оставить default-off.
Относительные `shade.db`/models разрешаются от `/var/lib/shadeai`. Ключи не писать
в командную строку, unit-файлы или отчёты. Core читает `.env` через pydantic;
`EnvironmentFile` не используется, чтобы не смешивать два разных формата dotenv.

```bash
sudo install -m 644 /opt/shadeai/deploy/shadeai.service /etc/systemd/system/
sudo install -m 644 /opt/shadeai/deploy/shadeai-backup.service /etc/systemd/system/
sudo install -m 644 /opt/shadeai/deploy/shadeai-backup.timer /etc/systemd/system/
sudo install -d /etc/systemd/journald@shadeai.conf.d
sudo install -m 644 /opt/shadeai/deploy/journald@shadeai.conf.d/limits.conf /etc/systemd/journald@shadeai.conf.d/
sudo systemd-analyze verify /etc/systemd/system/shadeai.service /etc/systemd/system/shadeai-backup.service /etc/systemd/system/shadeai-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now shadeai.service shadeai-backup.timer
```

Один Uvicorn process/worker на SQLite: не добавлять `--reload`/workers>1 и второй
экземпляр Core. Миграции upgrade head выполняются до готовности HTTP. Дашборд по
`http://<Pi-IP>:8000/`, API `/api/v1`, без Node/reverse-proxy в runtime. Bearer
защищает данные; публичные файлы не содержат ключа. Production `/docs`/`/redoc`
отключены (не загружают CDN), `/openapi.json` локальный. Неизвестный API/путь —404,
не HTML fallback. CSP только свой origin; index без долгого кэша, hashed assets
immutable. В dev без WEB_DIST_PATH поведение прежнее; интерактивная dev-документация
может обращаться к CDN, для автономного развёртывания использовать production-режим.

Служба слушает LAN: ограничить порт8000 доверенной локальной сетью в firewall,
не пробрасывать в интернет. `IPAddressDeny/Allow` ограничивают **исходящие и входящие**
адреса процесса локальными сетями; реальная поддержка cgroup/BPF и DNS/IPv6 требует
проверки на Pi. Эти настройки не изолируют другие службы, включая HA/системный DNS.

MemoryHigh2560M/MemoryMax3072M ограничивают **весь cgroup Core с дочерними процессами**.
Это предохранитель, не измеренный бюджет и не обещание совместимости LLM+STT+HA на4GB.
Сначала измерить фактическую RAM/охлаждение; OOM или restart считать отказом.
Остановка даёт60с на worker/child/SQLite. Повторный HA-запрос после unknown не делается.

Логи Core ограничены LOG_MAX_BYTES/LOG_BACKUP_COUNT; консоль уходит в отдельный
`journalctl --namespace=shadeai -u shadeai.service`. Для namespace задано32MiB
persistent/8MiB runtime, retention14дней/KeepFree4G; это не абсолютный резерв диска
при чужих записях. Общий journald не перенастраивается. Проверить реально занятый
объём после первой загрузки. HTTP access-log отключён.

## Backup и восстановление

Таймер ежедневно04:00±15мин по **часовому поясу ОС**, Persistent=true. До его
включения проверить timezone. Копии по умолчанию `/var/lib/shadeai-backups`,7штук;
при ином DB_URL изменить `--source` в backup unit. Первая ручная проверка:

```bash
sudo systemctl start shadeai-backup.service
sudo journalctl --namespace=shadeai -u shadeai-backup.service
sudo systemctl list-timers shadeai-backup.timer
```

Инструмент stdlib SQLite Backup API читает source mode=ro, учитывает committed WAL,
затем integrity_check/foreign_key_check/ревизию Alembic; копия standalone DELETE.
Незакоммиченные изменения не включаются. Для SQLite shared-memory source-каталог
доступен service-user на запись, но соединение БД read-only. Новый файл600/каталог700,
публикация только после проверки без overwrite. Проверяется запас4GiB+размер до
начала и4GiB при копировании, timeout120с; чужая запись может расходовать резерв.
На ошибке существующие копии не удаляются. После успеха retention затрагивает только
свои `shade-backup-<UTC>-<uuid>.sqlite3`, чужие имена/symlink сохраняются. Не хранить
ручные копии под этим зарезервированным шаблоном.

Копии содержат приватные данные Core; не отправлять их в git/облако. `.env`/Keystore/
модели не входят в копию: настройки и ключ владельца хранить отдельно локально с
закрытыми правами. Копия на том же носителе защищает от логической ошибки, для отказа
носителя нужен второй локальный диск и отдельная проверенная копия.

Для восстановления остановить Core, сохранить старую БД **вместе с её WAL/SHM**,
создать новое имя, проверить результат и только затем сменить DB_URL в закрытом.env:

```bash
sudo systemctl stop shadeai.service
sudo -u shadeai /usr/bin/python3 /opt/shadeai/scripts/sqlite_backup.py restore --source /var/lib/shadeai-backups/<копия>.sqlite3 --destination /var/lib/shadeai/restored/new.db
sudoedit /var/lib/shadeai/.env
# DB_URL=sqlite+aiosqlite:////var/lib/shadeai/restored/new.db
sudo systemctl start shadeai.service
```

В команде заменить `<копия>` конкретным именем. Существующие destination/WAL/SHM/journal
и symlink отклоняются; прежняя БД не перезаписывается. SHA результата относится к
новому физическому файлу: SQLite header может отличаться при повторном backup;
проверять данные/схему/целостность. Миграции при старте могут обновить старую копию,
поэтому исходный backup сохранять неизменным. Активные/неизвестные HA-действия и PIN
нельзя считать безопасными для повтора после восстановления: сначала вручную проверить
устройства, отключить исполнители/доступ, затем принимать новую работу.

## Аппаратная приёмка

На Pi: boot→Core/Web; фактические версии/HA/часовой пояс; локальный browser/Android;
физический свет с явным согласием; уведомление→перезапуск→сохранение; backup→новаяБД→
старая запись доступна; journal/disk/RAM/cgroup; отключённый интернет. Записать условия
и результаты в отчёт08. Пока этого нет, чекбокс TASK-08 остаётся открытым.
