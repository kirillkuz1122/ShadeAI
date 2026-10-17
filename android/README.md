# Shade AI — Android-клиент

Клиент Shade AI на Kotlin + Jetpack Compose: настройки адреса/ключа, проверка Core и авторизации, служебная тестовая отправка. Room-буфер и NotificationListener пока требуют TASK-10–13. TASK-09 реализована и проверена на эмуляторе без физического телефона; аппаратная приёмка остаётся открытой. [Отчёт TASK-09](../docs/reports/task-09.md).

## Сборка

Нужны **JDK 17**, Android SDK Platform 35 и Build Tools 34.0.0. Проект использует AGP 8.7.3, Kotlin 2.0.21 и Gradle Wrapper 8.10.2; [совместимость AGP](https://developer.android.com/build/releases/agp-8-7-0-release-notes).

В Android Studio (Ladybug или новее): откройте `android/`, выберите JDK 17 для Gradle, установите SDK-компоненты через SDK Manager, затем соберите `app` или запустите на устройстве. Подходит Android 8.0/API 26 и новее.

Можно собрать из терминала, без установки IDE:

```bash
cd android
# JAVA_HOME должен указывать на JDK 17, ANDROID_HOME — на установленный SDK.
./gradlew :app:assembleDebug :app:lintDebug --no-daemon --max-workers=2
```

Для локальных инструментов, установленных при TASK-03 в этом проекте (Linux):

```bash
cd android
env -u ANDROID_SDK_ROOT \
JAVA_HOME=/usr/lib/jvm/java-17-openjdk \
ANDROID_HOME="$PWD/.gradle/sdk" \
ANDROID_USER_HOME="$PWD/.gradle/android-home" \
GRADLE_USER_HOME="$PWD/.gradle/user-home" \
./gradlew :app:assembleDebug :app:lintDebug --no-daemon --max-workers=2
```

SDK и кэш Gradle в `.gradle/` не входят в git и не появятся при новом клонировании. На другом компьютере установите инструменты через [Android Studio / Command-Line Tools](https://developer.android.com/studio) и укажите свой путь SDK. `local.properties`, если используется, тоже не коммитится. Если унаследованная `ANDROID_SDK_ROOT` указывает на другой SDK, Gradle откажет из-за конфликта: пример выше удаляет эту переменную только для команды сборки.

Debug APK: `app/build/outputs/apk/debug/app-debug.apk`. Установка на подключённый телефон:

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.shadeai.app/.MainActivity
```

DTO health синхронизирован с TASK-06. В TASK-09 Bearer добавлен к защищённым запросам UI и NotificationListener, но health выполняется без ключа. Управления устройствами в Android пока нет.

## Настройки и проверка подключения (TASK-09)

1. Запустите [Shade Core](../core/README.md) на компьютере или Pi. Введите его доверенный локальный адрес: http(s)://host:port либо с /api/v1/. Путь нормализуется к /api/v1/. Логин/пароль, query, fragment, другой путь и пробелы внутри адреса запрещены; значение ошибки не выводит исходный URL.
2. Введите SHADE_API_KEY из локального файла настроек Core: не менее 32 печатных ASCII-символов без пробелов. Поле скрыто, после сохранения очищается. Нажмите «Сохранить и проверить».
3. Проверяются независимо открытый health и защищённый GET notifications?limit=1. «Ключ принят» отделён от статуса Core/БД/HA. 401 означает отказ ключа Core; HA_AUTH_FAILED в health — отдельная ошибка токена HA. Отказ HA не мешает доставке уведомления в Core. 5xx, redirect, таймаут, TLS и отсутствие соединения отображаются безопасными сообщениями, без текста исходного исключения/ответа.
4. «Отправить тестовое уведомление» отправляет одну служебную запись Ozon без личных данных, со свежим UUID event_id и временем. Для неё не нужен доступ к уведомлениям телефона. Stored/duplicate показываются как сохранение с ID; skipped — как пропуск по правилам Core. Новый ручной клик — отдельная служебная запись, автоматического повтора нет.
5. Адрес и зашифрованный ключ сохраняются после остановки процесса. Пустое поле ключа оставляет прежний ключ только для того же нормализованного адреса. Для нового адреса введите ключ заново. «Удалить ключ» удаляет сохранённый шифротекст; последующие защищённые запросы без ключа не отправляются. Удаление не отзывает уже отправленный запрос и ключ на самом Core.

**Хранение:** SharedPreferences MODE_PRIVATE сохраняет адрес и AES-GCM шифротекст с IV; AES-ключ находится в Android Keystore, исходный SHADE_API_KEY на диск не записывается. AAD привязывает шифротекст к адресу. При повреждении хранилища/недоступном Keystore показывается ошибка без автоматического сброса; удалите ключ и введите заново. Удаление логическое, защиты от компрометированного устройства/памяти процесса не заявляется. Настройки не переносятся на другое устройство автоматически.

Автоматический Android backup выключен (allowBackup=false); XML-правила исключают файлы, БД и preferences из cloud backup и device transfer для соответствующих API. Результат системного backup на устройствах разных производителей ещё не проверялся. Правила нужны и для будущего Room-буфера: он не должен попадать в облако.

Состояние экрана хранится в ConnectionViewModel/StateFlow и собирается через collectAsStateWithLifecycle. Редактирование отменяет предыдущую проверку и не применяет её запоздалый результат. API-клиент получает снимок адреса/ключа, использует общий транспорт без хранения idle-соединений, connect/read/write/call timeout 3/5/5/10 секунд, без redirect, proxy и автоматических повторов. HTTPS сохраняет штатную проверку сертификатов. Адрес должен принадлежать вашей LAN/доверенной VPN; частная сеть DNS/IP автоматически не проверяется. Для HTTP действует точный список Network Security Config ниже.

Доступ к уведомлениям включается вручную в системных настройках. Выбор приложений и экран разрешения — TASK-10, обработка/фильтрация до Room — TASK-11, надёжные повторы/очистка — TASK-12. В исходном allowlist Ozon/Wildberries/Яндекс Go; банки и мессенджеры исключены. Перехваченные события пока используют серверный отпечаток полей, UUID для Room появится в TASK-11. Timestamp — Instant без общего SimpleDateFormat. Успешный служебный POST не подтверждает перехват/фоновые повторы с телефона.

## Локальный транспорт

[Network Security Config](app/src/main/res/xml/network_security_config.xml) запрещает HTTP по умолчанию и разрешает его только для точных адресов: `192.168.1.100`, `10.0.2.2`, `127.0.0.1`, `localhost`, `shade.local`. Это адрес Core по умолчанию и локальная разработка; поддомены не разрешаются автоматически. HTTPS использует штатную проверку сертификатов Android.

Для другого IP сервера добавьте именно этот адрес в `domain-config` файла выше и пересоберите APK либо используйте HTTPS с доверенным сертификатом. Не включайте HTTP глобально и не отключайте проверку TLS. Правила конфигурации — в [документации Android](https://developer.android.com/privacy-and-security/security-config).

Для эмулятора используйте `http://10.0.2.2:8000/api/v1/`, для USB-подключения можно перенаправить порт:

```bash
adb reverse tcp:8000 tcp:8000
```

После перенаправления адрес в приложении: `http://127.0.0.1:8000/api/v1/`.

## Структура

```
app/src/main/java/com/shadeai/app/
├── ShadeApp.kt              # Application: синглтоны (Room)
├── MainActivity.kt          # lifecycle ViewModel + Compose-экран подключения
├── core/
│   ├── config/                  # валидация адреса, Keystore/настройки, исходный allowlist
│   └── network/                # Retrofit API + DTO (kotlinx-serialization)
├── data/db/AppDatabase.kt   # Room: буфер неотправленных уведомлений
├── service/ShadeNotificationListener.kt  # перехват уведомлений → Shade Core
└── ui/                      # ConnectionViewModel/Screen и фирменная тема
```

## Что дальше (roadmap MVP v0.2)

- Экран выбора отслеживаемых приложений (сейчас — захардкоженный список в `Allowlist`).
- Лог перехваченных уведомлений в UI.
- Wake word / голосовой ввод (MVP v0.5).

## Проверки без физического телефона

JVM-тесты URL/HTTP и Android-тесты Keystore/настроек используют зависимости только test/androidTest. Для эмулятора API 35 выполните с теми же JDK/SDK из раздела сборки:

```bash
./gradlew :app:testDebugUnitTest :app:connectedDebugAndroidTest :app:lintDebug --no-daemon --max-workers=2
```

Android-тесты используют отдельный preferences-файл, не заменяют сохранённый ключ UI. В эмуляторе проверяются реальные Android Keystore и Network Security Config, но не поведение конкретного физического телефона.

Для полного UI-сценария сохранены [временный Core](checks/core_server.py) и [ADB-проверка](checks/check_emulator.py). Из корня проекта запустите Core в отдельном терминале:

```bash
core/.venv/bin/python android/checks/core_server.py
```

Он читает только синтетическое окружение, пишет в временную БД/логи под core/.pytest_cache, слушает 127.0.0.1:8000, HA отключён. Рабочие .env/БД/HA не используются. Не запускать одновременно с pytest, очищающим свой временный каталог. Перед повторным полным UI-сценарием перезапустите стенд: проверка требует пустой БД.

Запустите установленный AOSP-эмулятор emulator-5554, установите свежий APK, затем:

```bash
python android/checks/check_emulator.py
```

Скрипт требует уже установленный SDK в android/.gradle/sdk, проверяет виртуальное устройство, делает adb reverse, меняет только синтетические настройки эмулятора и отправляет служебную запись в отдельный Core. Проверяет экран, encrypted prefs, restart, 401/HA, URL/HTTP-политику, отсутствие сети, привязку к адресу, удаление и logcat. Временный снимок — android/.gradle/task09-checks/emulator.png. После проверки остановите Core через Ctrl+C и эмулятор; временная БД удаляется при штатном завершении. Рабочий телефон скрипту не подключать.

Для закрытия TASK-09 позднее повторить настройку/проверку/служебную отправку и перезапуск на физическом телефоне, записать модель и версию Android. TASK-03 также ждёт аппаратной приёмки. Raspberry Pi для разработки и эмуляторной проверки не требуется.
