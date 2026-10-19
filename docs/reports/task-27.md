# TASK-27 — инструменты и протокол приёмки

**Статус:** программная подготовка выполнена.14дневная эксплуатация и аппаратная
приёмка **не начаты/не выполнены**. Чекбокс27 открыт,17задач/все полные этапы не приняты.

## Сделано

[Протокол](../acceptance.md) связывает открытые DoD03/08/09/11/13/14/16/18–27
с реальными проверками: Pi/телефон/HA/CalDAV/датчики/nativeLLM/STT/ключевая клавиатура,
качество/скорость/приватность/энергия/14дней. Длительный отсчёт начинается после
отказных тестов/restore, реальные рестарты/вмешательства не складываются в14дней.

`scripts/acceptance_probe.py` — stdlib Python3.11+, read-only:
- Только числовой LAN IP health, GET без DNS/proxy/auth/redirect/retry; TLS/IP SAN
  проверяются. Общий HTTP deadline8с, response≤72KiB, никаких HA-команд.
- Фиксированные health enum/числа, host RAM/Swap/uptime/boot hash/UTC/monotonic.
  По явному своему PID — RSS family≤128процессов/256threads, проверка start_ticks;
  опциональный cgroup v2 memory.current/peak/swap.current/oom_kill. Никаких argv/
  env/.env/БД/rawответов/аудио/ключей/URL в данных.
- Новый JSONL600/каталог700,≤32MiB/20161точка/1536байт на строку; памяти не растёт
  с длительностью. Default1точка, ресурсы:4GiB+32MiB до/4GiB во время, RAM64MiB.
  Пропажа/PIDreuse/ресурсы/прерывание завершают собственный сбор; чужое не чистится.
- Короткие наблюдаемые разрывы/смена uptime/часов отмечаются. Null/unknown не равны
  нулю или готовности; sampling может пропустить короткий отказ/пик. RSS sum не
  заменяет весь cgroup/системную RAM. Health latency не равна задержке HA-команды.
- Платформа из device-tree+aarch64, компьютер development_host. Hardware_acceptance
  всегдаfalse; LLM ready не подтверждает inference/качество. Нативные модельные
  измерения/ваттметр/14дней проверяются отдельно.

## Фактические проверки

-18новыхизолированныхтестов PASS наPython3.14 иPython3.11/network none: локальность/
  публичные IP/учётные данные/путь/порты, отсутствие auth/proxy/DNS, redirect/bodycap/
  усечённый HTTP, sanitization, закрытый/new output, resource-stop, PID/children/
  cgroup/разрывы/лимиты. TCP в pytest запрещён, ответы/ресурсы тестов синтетические.
- **Полный498Core/Python3.14 PASS**, ruff app/tests/migrations/probe/QA PASS. Web
  и Android source не менялись; предыдущий Webbuild480/Android82JVM/APK/lint сохранён.
  Полный Python3.11 был480 в TASK-08, новые18probe на3.11 проверены отдельно.
- Настоящий /proc и **два GEThealth собственного процесса Core**, интервал1с,
  maxRSSfamily122580992байт (~117MiB), maxстрока816байт. Hostdevelopment,
  hardwarefalse/nativefalse/cgroupfalse;HA намеренно недоступен,2degraded/0ok/0errors,
  **не healthy/full-system PASS**. Тот же стенд дополнительно проходит restart/
  WALbackup/newrestore. [JSON](task-27-probe.json). TemporaryJSONL/БД удалены, Core
  остановлен. Замер компьютера без LLM/STT не экстраполировать на Pi4GB.

## Следующий доступный шаг

При сверке mvp обнаружены ещё открытые программные OS-критерии19 (экран результата)
и21 (системная доставка подсказки), несмотря на общий APK/lint после23–26. Их можно
допроверять сохранённым APK на read-only AVD/синтетическом Core без моделей и новых
Gradle-сборок. Настоящий Android→GGUF→клиенты, телефон/Pi/длительность остаются открытыми.
После доступных проверок подготовить07:10сводку; после неё ждать Кирилла.

Основания: [Python http.client](https://docs.python.org/3.11/library/http.client.html),
[Linux proc](https://docs.kernel.org/filesystems/proc.html),
[cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html).
