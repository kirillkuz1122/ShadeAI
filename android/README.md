# Shade AI — Android-клиент

Скелет клиента Shade AI на Kotlin + Jetpack Compose: экран адреса/health, Room-буфер и код NotificationListener. Авторизация и надёжная доставка уведомлений ещё запланированы в TASK-09–13; наличие этих файлов не означает готовность MVP v0.2.

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

## Первый запуск

1. Запустите [Shade Core](../core/README.md) на компьютере или Pi.
2. В приложении укажите адрес с `/api/v1/`, например `http://192.168.1.100:8000/api/v1/`, и нажмите «Проверить связь». При нажатии адрес сохраняется в SharedPreferences; доступность health не требует API-ключа.
3. Закройте процесс приложения и откройте снова: адрес должен сохраниться. Проверку на конкретном телефоне фиксируйте в [отчёте TASK-03](../docs/reports/task-03.md).

Доступ к уведомлениям включается вручную в системных настройках. Текущий экран не открывает запрос разрешения автоматически; полноценная настройка телефона ещё предстоит в TASK-09–10.

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
├── MainActivity.kt          # экран статуса и настройки адреса сервера
├── core/
│   ├── config/ServerPrefs.kt   # SharedPreferences: адрес сервера, белый список приложений
│   └── network/                # Retrofit API + DTO (kotlinx-serialization)
├── data/db/AppDatabase.kt   # Room: буфер неотправленных уведомлений
├── service/ShadeNotificationListener.kt  # перехват уведомлений → Shade Core
└── ui/theme/                # фирменная палитра (docs/brand.md)
```

## Что дальше (roadmap MVP v0.2)

- Экран выбора отслеживаемых приложений (сейчас — захардкоженный список в `Allowlist`).
- Лог перехваченных уведомлений в UI.
- Wake word / голосовой ввод (MVP v0.5).
