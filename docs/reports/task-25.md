# TASK-25 — полностью локальная голосовая команда

**Статус:** программный контур реализован и проверен; полная TASK-25 открыта по настоящей STT-модели/речи/телефону/Pi/HA. Эта запись сопровождает отдельный коммит после da06bca. Следующая доступная программная задача — TASK-26. Никаких новых моделей/пакетов/SDK не скачано, диск~6.5GiB.

**Итог:**428 Core/Python3.14 и3.11 network none,ruff;31новый voice/engine тест; Android50focused/68штатныхJVM/offlineAPK/KSP/manifest/lint0errors3warnings3info. [APK SHA-256](task-25-android.json). Настоящие HTTP Core↔фиктивныйHA/restart/UUID/unknown/privacy PASS,2фиктивные команды, [JSON](task-25-loopback.json). STT там синтетический.

**AOSP35/read-only:** AudioRecord дал89344/89088PCMframes16kHz, rawWAV прошёл настоящий Core; preview не исполняет, confirmed=true выполняет один раз, GET не повторяет, unknown/PAUSE/401/privacy PASS. [OS JSON](task-25-android-emulator.json), APK SHA совпадает с f3d8f14971862d2141680ea91bc109216263d8f30fb7b8381b8a45410cdbfb84. Host audio выключено, STT/HA синтетические; эти фреймы не являются распознанной реальной речью/проверкой телефона. Селектор подключения стенда исправлен: после добавления новой навигации прежние верхние поля были обрезаны; поля показываются целиком, IME закрывается только если открыт.

Ниже дизайн/границы и хронология. Native Vosk не установлен/не запускался. Для будущего измерения готов checks/check_stt.py: уже подготовленные WAV/model/manifest, без HA, latency/peakRSS/expected intent, без сохранения транскрипта и перезаписи отчётов. Голосовой parser в этом срезе строгий, не LLM-NLU.

## Программный срез

Android AudioRecord PCM16/16kHz/mono, запись только по кнопке до10сек, в RAM без аудиофайла; runtime RECORD_AUDIO, остановка/очистка при STOP/смене Core. POST /voice с raw audio/wav и X-Request-ID; отдельный увеличенный таймаут STT, никакого облачного fallback. Результат распознавания и команда показываются владельцу для отдельного подтверждения. Wake word/произвольный разговор/сложные команды не входят в этот срез.

Core: default VOICE_ENABLED=false, отдельный явный alias→light.* список, никаких свободных params/авторасширения целей. Для этого среза намерение распознаётся строго по фразе «включи/выключи <явный alias>», без догадок/LLM. Нераспознанная/составная/неразрешённая фраза не выполняется. Это более узкая реализация, чем целевые архитектурные примеры с воротами; LLM-разбор голоса остаётся расширением, не выдаётся за написанный.

STT: optional Vosk0.3.45, только явно подготовленная локальная small ru модель и SHA-256 manifest; Model(model_path), никогда Model(lang)/download API. Отдельный CPU child с ограничением virtual memory/CPU/timeout, без наследования ключей/proxy и без Python-сети. PCM/хеширование/декодирование вне HTTP event loop. Один STT одновременно, проверка доступной памяти до запуска и во время, kill/reap при timeout/cancel. STT не выгружает чужую LLM и не меняет очередь уведомлений; совместный RSS/скорость/OOM проверять отдельно на Pi4GB, лимиты процесса не равны общему бюджету.

Preview подтверждается только с текущим policy_scope и confirmed=true, TTL60сек. Durable request UUID/payload hash/цель/действие/статус без аудио/транскрипта; dispatching до общего execute_command/audit и сети, повтор не посылает команду снова. Restart in-flight→unknown, pending→cancelled; нельзя угадать выполнение по HTTP timeout. GET статуса/отмена pending доступны отдельно. Текстовая JSON-команда — явно диагностический/ручной ввод, не доказательство STT. В обычном Android сценарии передаётся только WAV.

## Источники выбора STT

- [Vosk installation](https://alphacephei.com/vosk/install): существующие Linux/ARM64 bindings и PCM16kHz16bit mono; страница содержит старый диапазон Python, совместимость текущих Python без проверки не обещать.
- [Официальные модели](https://alphacephei.com/vosk/models): small ru0.22, опубликованный архив45MB, Apache2.0; указанная оценка памяти small-моделей~300MB является данными автора, не нашим измерением.
- [Пример API](https://raw.githubusercontent.com/alphacep/vosk-api/master/python/example/test_simple.py), [реализация Model](https://raw.githubusercontent.com/alphacep/vosk-api/master/python/vosk/__init__.py), [PyPI0.3.45](https://pypi.org/project/vosk/): explicit local path/SetWords и ARM64 wheel. Native inference пока не запускался, пакет не установлен.

## Открытая приёмка

Реальные русские записи/микрофон/качество STT/устройство HA/телефон/отключённый интернет/совместная нагрузка Pi4GB ещё не проверены. Фейковый STT в тестах или ручная текстовая команда не заменяют эти критерии. После доступной программной25 — TASK-26; TASK-27 требует оборудования и длительности.


## Промежуточные проверки

Core428/Python3.14 иruff PASS.31новых voice/engine тестов: WAV bounds, строгие фразы/согласие/ID/policy/expiry/cancel/restart/timeout/audit/result-write и конкурентный confirm без DB-lock во время HA; синтетический stdio child проверяет закрытое окружение, busy/cancel/reap/timeout/RAM/manifest. Настоящего Vosk inference не было. Python3.11 network none перепроверяется.

Android AudioRecord/PCM/WAV/controller/экран/RECORD_AUDIO/отдельный STT-timeout написаны.50focused JVM и все Kotlin/Compose PASS: raw WAV/Bearer/UUID/confirmed=true, STOP/сменаCore/отмена до микрофона/401/unknown без повтора. Микрофон работает только пока экран RESUMED, данные не идут в SavedState/WorkManager/файлы. Штатные APK/KSP/manifest/JVM/lint проверяются; OS-микрофон/доставкаWAV/реальныйSTT ещё не приняты. Кэш временно нужен; новых загрузок нет, диск~6.5GiB.


## Уточнение приватности 19 октября: потеря фокуса

По результату TASK-26 обнаружен риск: Overview может оставлять Activity RESUMED,
поэтому одного ON_PAUSE недостаточно. VoiceRoute теперь закрывает recorder/job и
очищает текст также при потере фокуса окна; возврат открывает только экран, запись
требует нового явного нажатия. Старое поведение микрофона отдельно не воспроизводилось.

Новый APK 8df0ac55…: offline Kotlin/Compose/APK/82JVM/lint PASS. На read-only AOSP35
проверен настоящий AudioRecord: через1с после Overview app-op не running, спустя10с
STT вызовов0; возврат не записывает, новая явная запись даёт1синтетический STT-вызов,
HA-команд0. Второй Overview очищает транскрипт. Core настоящий, STT/HA синтетические,
нативная речь/телефон/Pi не проверены. [JSON](voice-focus-2026-10-19.json),
воспроизведение: voice_server.py + check_voice_focus.py через Corevenv, только
одноразовый read-only AVD. Свои сервер/AVD остановлены.
