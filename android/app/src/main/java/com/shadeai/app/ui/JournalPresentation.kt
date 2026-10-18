package com.shadeai.app.ui

import com.shadeai.app.data.db.DeliveryStatus
import com.shadeai.app.data.db.JournalSnapshot
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

fun journalTime(time: Long): String = DateTimeFormatter.ofPattern("dd.MM.yyyy, HH:mm:ss", Locale.forLanguageTag("ru"))
    .withZone(ZoneId.systemDefault()).format(Instant.ofEpochMilli(time))

fun deliveryLabel(status: DeliveryStatus): String = when (status) {
    DeliveryStatus.PENDING -> "Ожидает отправки"
    DeliveryStatus.FAILED -> "Не подтверждено"
    DeliveryStatus.SENT -> "Получено Core"
    DeliveryStatus.SKIPPED -> "Пропущено Core"
    DeliveryStatus.REJECTED -> "Отклонено Core"
}

fun deliveryError(category: String?): String? = when (category) {
    null -> null
    "credentials" -> "Ключ Core не задан. Сохраните настройки подключения."
    "configuration" -> "Проверьте адрес и сохранённый ключ Core."
    "tls" -> "Сертификат Core не прошёл проверку. Проверьте подключение."
    "receipt" -> "Ответ Core не подтвердил доставку. Проверьте совместимость сервера."
    "network" -> "Нет подтверждения от Core. Проверьте локальную сеть и сервер."
    "http_401", "http_403" -> "Ключ Core не принят. Сохраните правильный ключ в настройках."
    "http_400", "http_422" -> "Core отклонил формат уведомления. Автоматического повтора нет."
    "http_409" -> "UUID уже связан в Core с другим содержимым. Автоматического повтора нет."
    "http_413" -> "Уведомление превышает предел Core. Автоматического повтора нет."
    "http_404" -> "API Core не найден. Проверьте адрес подключения."
    "http_408" -> "Core не успел подтвердить запрос. Запланирована повторная попытка."
    "http_425", "http_429" -> "Core временно ограничил приём. Запланирована повторная попытка."
    else -> {
        val code = category.removePrefix("http_").toIntOrNull()
        when {
            category.matches(Regex("http_5[0-9]{2}")) -> "Временная ошибка Core (HTTP $code). Запланирован повтор."
            category.matches(Regex("http_3[0-9]{2}")) -> "Core вернул перенаправление. Укажите конечный адрес."
            category.matches(Regex("http_4[0-9]{2}")) -> "Core отклонил запрос (HTTP $code). Проверьте подключение."
            else -> "Не удалось доставить уведомление. Проверьте настройки подключения."
        }
    }
}

fun queueMessage(snapshot: JournalSnapshot, now: Long = System.currentTimeMillis()): String {
    if (snapshot.queued == 0) return "Очередь пуста"
    val gate = snapshot.control?.takeIf { it.revision == snapshot.revision }
    return when {
        gate?.blocked == true -> "Отправка приостановлена. Сохраните настройки подключения."
        gate != null && gate.nextAttemptAt > now -> "Повтор не раньше ${journalTime(gate.nextAttemptAt)}"
        else -> "Очередь ожидает отправки. Для доставки нужна связь с Core."
    }
}
