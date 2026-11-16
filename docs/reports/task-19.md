# TASK-19 — результаты Core в клиентах

**Статус на19октября:** Web/Android программно реализованы. Общие Gradle/Kotlin/Compose/APK/lint проверены в23–26 (82JVM); дополнительно полный AOSP35/read-only экран19→настоящийCore PASS на сохранённом APK8df0ac55…, без новой сборки. **TASK-19 открыта** по единому Android→Core+nativeGGUF→оба клиента и физическому телефону/Pi;18качество не принято. [OS JSON](task-19-android-os.json).

## Реализация

- Web вместо сырого JSON показывает ограниченную версию1: категорию, приоритет, subject/location/service, время/цитату/часовой пояс. Diagnostic явно отделён от LLM. Неизвестная версия/неверные типы/несогласованный intent/time/action_authorized дают безопасную подпись, исходный JSON не выводится. Ошибки LLM переведены в фиксированные русские сообщения, неизвестный код не отображается.
- Точное время показано в timezone результата; date_only отображается как календарная дата без перевода полуночи, unresolved не получает выдуманную дату. Проверены несуществующая дата и часы24:00, неизвестный пояс, будущая схема, неверные типы и authorization=true. Модельный результат описательный, команду HA не создаёт.
- Карточка Web опрашивается существующим useResource каждые5с, по404/401 данные очищаются; ключ/страница/закрытие сохраняют прежнюю отмену запросов. Извлечённые сущности только в деталях, в общей ленте не добавлены.
- Android: отдельный экран «Результаты Core» с подключения. Защищённые GET списка (20 строк/страница) и карточки по серверному ID используют общий ShadeApi.create и явный снимок URL/ключа/revision. Room/WorkManager/источники/доставка не меняются. SENT локального журнала не считается processed.
- CoreResultsController отменяет предыдущий запрос при смене карточки/страницы/настроек, проверяет generation/revision перед применением ответа, очищает данные по STOP/выходу и ошибке. Foreground-поллинг5с только при STARTED; новых фоновых workers нет. SharedPreferences listener активен только на экране. Ключ/URL находятся в локальном снимке запроса, не в UI-state/SavedState/логах; DTO/state/credentials.toString редактированы.
- Android показывает статус, число попыток, UUID, безопасную ошибку и те же известные поля schema1. Неизвестные схемы не выводятся JSON. Открытие серверной истории не запрашивает разрешение NotificationListener и не расширяет источники. В SavedState сохраняется прежний маршрут; payload/ключ туда не записываются.
- API Core и схема БД не менялись: используются существующие GET /notifications и /notifications/{id}.

## Проверки

1. `cd web && npm run build` — успешно, `node checks/processing.mjs` — PASS: типы/версия/action/intent, время/календарные даты, diagnostic, безопасные ошибки.
2. Chromium, существующий системный браузер, синтетические browser routes: pending→processed на открытой карточке, поля/пояс07:00, мобильные320px без overflow, отсутствие сущностей после закрытия, неизвестная версия, diagnostic, failed, очистка по404 и401. **PASS**, 15 запросов карточки, JS-ошибок/внешних запросов нет. HTTP401/404 видны в консоли браузера как ожидаемые ответы, не как pageerror. Снимок проверен визуально; `web/output/playwright/task19-result-mobile.png` игнорируется.
3. `python android/checks/check_results_jvm.py --compile-app` — **11 JUnit passed**; Kotlin2.0.21/JDK17/serialization+Compose compiler2.0.21. Все production Kotlin/Compose-исходники скомпилированы с настоящим SDK35/зависимостями из существующего кэша. Единственное предупреждение — прежний deprecated ConnectivityManager.allNetworks.
4. JVM-тесты проверяют: точный пояс/date_only/unresolved, malformed/unknown schema/action/intent/noise, безопасные ошибки; страницы/карточку, очистку при STOP и401/404, запоздалый неотменяемый ответ старого сервера, реальные Retrofit GET/Bearer/DTO на синтетическом MockWebServer. Сервер слушает только тестовый loopback; production Core/HA не вызываются.
5. Core после последнего изменения — **272 pytest**, ruff успешны. Этот срез клиентов Core не меняет. Проверки не заменяют APK/Gradle/lint/AVD или полный конвейер с моделью.

## Воспроизведение без скачиваний

Web: из web/ запустить локальный Vite на127.0.0.1:5187, открыть браузер через уже установленный Playwright CLI с `checks/playwright.config.json`, затем `run-code --filename=checks/check-results.js`; используется системный /usr/bin/chromium, backend подменён только синтетическими ответами. Полные команды в [Web README](../../web/README.md#результаты-извлечения-программная-часть-task-19).

Android: из корня `python android/checks/check_results_jvm.py --compile-app`. Загрузок нет, отсутствующий jar даёт понятную ошибку, а не установку. Максимальная heap компилятора512MiB (не полный RSS JVM), тестов128MiB. AAR-классы занимали **20693179 байт**, временные каталоги удалены после завершения. Бюджет извлечения100MiB, свободное место проверяется с резервом512MiB. Подробности в [Android README](../../android/README.md#результаты-core-программная-часть-task-19).

## Почему аппаратные/полные проверки открыты

Общий с Claude диск менялся от6.8GB до168MB. После удаления всех трёх собственных моделей и восстанавливаемых Android-артефактов освобождено суммарно около4.16GB, но общий запас продолжает меняться. Полная Gradle-сборка пересоздала бы около1.4GB кэша; сейчас её не запускаем. SDK/JDK/AVD и скачанные зависимости сохранены. Прямой Kotlin-стенд использует около21MB временных jar и не создаёт Gradle-кэш.

Когда будет достаточно места, нужны штатные assembleDebug/testDebugUnitTest/lintDebug и инструментальные lifecycle/настройки/интерфейсные проверки на одноразовом AVD, затем единый синтетический конвейер с локальной GGUF (скачивать только при безопасном запасе) и аппаратная приёмка телефона. До этого **не отмечать TASK-19 выполненной**.


Допроверка19октября в TASK-23: после появления свободного места прошли штатные offline assembleDebug/testDebugUnitTest/lintDebug текущего приложения (включая19/21/22/23):46JVM,0ошибокlint/3warnings/1info, APK/KSP/manifest merge и подписьv2 подтверждены. [Метаданные](task-23-android.json), [отчёт23](task-23.md). Прежнее ограничение только прямой компиляцией снято для этих пунктов; AVD/instrumented/OS-доставка/телефон/полныйGGUF-конвейер ещё открыты.


## Допроверка OS19 — 19 октября, PASS

Сохранённый APK8df0ac55… (последний voice-focus,безпересборки) на guarded read-only
AOSP35 подключён к отдельному настоящему Core/results_server.py.25синтетических
уведомлений, переходы разбора задаются напрямую QA-контролем, nativeLLM выключен.

Полный сценарий check_results_os.py PASS: pending→processing→processed в открытой
карточке/поля/пояс, unknown schema без JSON, diagnostic отдельно от LLM, failed
с безопасным неизвестным кодом,404 очищает текст, страницы20/4 после удаления,
STOP прекращает polling/возврат возобновляет,401 очищает список, prefs без исходного
текста/открытого ключа/ошибки, crash-buffer текущего прогона без падений, HA-команд0.
[JSON](task-19-android-os.json). История хранится в настоящем SQLite Core, приложение
не получало новую специальную test-сборку. Рабочий API/приложение не менялись.

Исходный QA-поиск кнопки исчерпывал6свайпов до низа20карточек; helper получил
ограничение24свайпа. Дополнительный диагностический dump был ошибочно запущен
одновременно с UiAutomation теста и вызвал crash **UiAutomator**, не Shade. Вторая
проверка увидела эту прежнюю запись. Финальный полный прогон выполнен последовательно
с очищенным перед стартом crash-buffer и прошёл целиком. Сведения не скрыты и
утверждение «приложение падало» из этого лога не делается.

Свои Core/AVD остановлены, временнаяБД/XML/reverse удалены. Загрузок/Gradle не было.
Это проверка Android UI/HTTP, не нативного качества18/телефона/Pi и не полного
уведомление→GGUF пути. Следующий доступный OS-срез21 — системная доставка подсказок.


## 16 ноября: системный захват, Qwen и показ после рестарта

[Протокол](task-19-native-staged-2026-11-16.json). Один временный SQLite store,
существующий APK8df0ac55… и QA publisher; AVD и модель работали по очереди.

1. В новом read-only AOSP35 выбран Ozon. Два синтетических системных уведомления
   прошли listener/WorkManager и обычный HTTP в Core; разные event_id, две строки pending.
2. AVD/Core остановлены. Core и штатный worker на той же SQLite запущены в `unshare -Urn`
   с pinned Qwen. Обе строки получили `failed`/`LLM_BAD_RESPONSE` после одной попытки.
   Отдельно через POST API подан контроль: `processed`, доставка через 8 минут,
   `action_authorized=false`. Старые отказы не переиграны. Журнал HA пуст.
3. Core с выключенной моделью снова открыл ту же SQLite. Новый read-only AVD и
   Chromium показали те же три ID/event_id, две ошибки и локальный разбор с поясом.
   Браузер читал реальные GET деталей, без подмены ответа, ошибок JS и внешних запросов.
   Первый Android-тест искал общий fallback; исправлено ожидание текста известного
   `LLM_BAD_RESPONSE`, повтор прошёл. Приложение не менялось.

Успешный контроль подан API: успешный разбор именно Android-уведомления, телефон,
Pi и качество TASK-18 остаются открытыми. Стенды остановлены, временная БД удалена.

Повтор из корня: существующие APK, Qwen, production `web/dist`, Chromium и readonly AVD.
Создать новый `mkdir -m 700 core/.pytest_cache/task19-native-work`; запустить
`core/.venv/bin/python android/checks/native_results_core.py serve` и отдельно
`python android/checks/run_emulator_guarded.py`. После загрузки AVD выполнить
`core/.venv/bin/python android/checks/check_native_results.py capture`, остановить оба стенда.
Из `core/` запустить `.venv/bin/python checks/run_native_guarded.py --seconds 120 --output <новый-json> -- .venv/bin/python ../android/checks/native_results_core.py infer`, затем с другим JSON и фазой `infer-control`.
После завершения native снова запустить `serve`, чистый guarded AVD и
`check_native_results.py display`. Chromium: отдельная сессия Playwright CLI с
`npm_config_offline=true` и прежним config, `open http://127.0.0.1:8003`,
`run-code --filename=checks/native-results.js`, `close` из `web/`.
После прогона остановить свои процессы, сохранить протокол и удалить свою тестовую БД.


## Повтор текстов Android-публикатора на Qwen с новой dev-схемой

[Два знакомых текста publisher](../../core/checks/eval-android-publisher-dev.json)
зарегистрированы как dev. Сравнение CLI с реальной Qwen, без нового AVD, Core или клиентов.
[База](task-19-publisher-base-dev.json) отклонила оба, как раньше на AVD.
[Категория + буквальное время](task-19-publisher-candidate-dev.json) дала один
валидный результат: `aosp-big` — доставка, «вечером»/`unresolved`, `action_authorized=false`.
Приоритет `low` расходится с разметкой `high`. Полное совпадение 0/2 в обоих вариантах.
`aosp-order` в обоих получил `LLM_BAD_RESPONSE`; [повтор отказа](task-19-publisher-diagnostics.json)
нашёл отличие регистра в `service`. Сырой вывод не сохраняли; это не подтверждает,
что слово по смыслу было названием службы. Схему рабочего Core не меняли.

[Guard базы](task-19-publisher-base-guard.json), [кандидата](task-19-publisher-candidate-guard.json),
[диагностики](task-19-publisher-diagnostics-guard.json) не прерывал прогоны.
Диск ~5.8 GiB, ниже порога AVD 6 GiB; новых файлов моделей/SDK нет. Успешный
Android→Core→оба клиента ещё не подтверждён.

Повтор из `core/`: `checks/evaluate_extraction.py --stage development --dataset checks/eval-android-publisher-dev.json`
с указанными `--model`/`--output` через `checks/run_native_guarded.py`, затем с
`--router-rules --time-literals` и новыми JSON. Для повтора отказа использовать
`checks/diagnose_extraction.py` с тем же `--dataset` и `--evaluation` кандидата.


## Сквозной тест AVD с экспериментальной схемой

[Протокол](task-19-candidate-e2e-2026-11-16.json). Два новых системных уведомления
синтетического publisher через listener/WorkManager и реальный HTTP попали в
отдельную SQLite как pending. После остановки AVD и HTTP-процесса штатный worker
на той же SQLite обработал обе строки offline Qwen (правила категории, буквальные
время и сервис включены только в `infer-candidate` стенда). Получены `processed`
и delivery, по одной попытке, UUID не изменились, HA audit 0. Контроль через API
не добавлялся; кандидат из `445da10`, модель по тому же SHA-256. Guard PASS.

Core запущен заново без модели. Чистый AOSP35 и Chromium показали обе записи
и локальный разбор с поясом; Web делал настоящие GET к Core, внешних запросов
и JS-ошибок нет. Повторное чтение API подтверждает `action_authorized=false`.
У одного события приоритет `low` всё ещё расходится с разметкой `high`;
показ сохранённого результата не доказывает точность извлечения.

Повторить предыдущий протокол capture → остановить AVD/Core → offline native,
заменив `infer`/`infer-control` одним `infer-candidate`; затем снова `serve`,
чистый AVD `display` и `checks/native-results.js` в Chromium. Использовались
сохранённые APK и Web dist, без сборок и загрузок. Свои процессы остановлены,
временная SQLite и браузерный снимок удалены. Рабочий Core не использует
эксперимент. TASK-19 открыта по физическому телефону/Pi и принятию схемы/качества.
