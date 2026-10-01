# Shade AI — Android-клиент

Kotlin + Jetpack Compose клиент Shade AI (MVP v0.2). Перехватывает уведомления через `NotificationListenerService`, буферизует в Room и отправляет на Shade Core.

## Сборка

1. Установи [Android Studio](https://developer.android.com/studio) (Ladybug или новее).
2. `File → Open` → выбери папку `android/`. Studio сама скачает Gradle 8.10.2 и зависимости.
3. Подключи телефон (Android 8.0+, USB-отладка) → `Run ▶`.

## Первый запуск

1. При первом старте система попросит дать приложению доступ к уведомлениям:
   `Настройки → Специальный доступ → Доступ к уведомлениям → Shade AI`.
2. В приложении укажи адрес сервера, например `http://192.168.1.100:8000/api/v1/`, и нажми «Проверить связь».
3. На Raspberry Pi должен быть запущен Shade Core (`core/README.md`).

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
