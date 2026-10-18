package com.shadeai.app.ui

import kotlinx.serialization.json.*
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

sealed interface CoreProcessing {
    data object Missing : CoreProcessing
    data object Diagnostic : CoreProcessing
    data object Unsupported : CoreProcessing
    class Extracted(val fields: List<Pair<String, String>>) : CoreProcessing {
        override fun toString() = "Extracted(redacted)"
    }
}

fun coreCategory(value: String?) = when (value) {
    "delivery" -> "Доставка"
    "transport" -> "Поездка"
    "calendar" -> "Встреча"
    "reminder" -> "Напоминание"
    "noise" -> "Не требует внимания"
    else -> "Не определена"
}

fun coreProcessingError(value: String?) = when (value) {
    null -> null
    "LLM_BAD_RESPONSE", "INVALID_RESULT" -> "Модель вернула неподтверждённые или неполные сведения"
    "LLM_TIMEOUT", "PROCESSOR_TIMEOUT" -> "Превышено время обработки"
    "LLM_CONTEXT_EXCEEDED" -> "Текст не помещается в контекст модели"
    "LLM_PROCESS_EXITED", "PROCESSING_INTERRUPTED", "LLM_CANCELLED" -> "Обработка была прервана"
    else -> "Не удалось обработать запись"
}

fun coreProcessing(raw: JsonElement?): CoreProcessing {
    if (raw == null || raw is JsonNull) return CoreProcessing.Missing
    return try { parseCoreProcessing(raw) } catch (_: Exception) { CoreProcessing.Unsupported }
}

private fun JsonObject.string(name: String, max: Int): String {
    val value = getValue(name) as JsonPrimitive
    require(value.isString)
    return value.content.also { require(it.isNotBlank() && it.length <= max && it.none { c -> c.code < 32 || c.code == 127 }) }
}
private fun JsonObject.optional(name: String, max: Int): String? =
    if (getValue(name) is JsonNull) null else string(name, max)

private fun parseCoreProcessing(raw: JsonElement): CoreProcessing {
    val value = raw.jsonObject
    val processor = value.string("processor", 16)
    val llm = value.getValue("llm").jsonPrimitive.also { require(!it.isString) }.boolean
    if (processor == "diagnostic" && !llm) return CoreProcessing.Diagnostic
    require(processor == "llm" && llm)
    require(value.getValue("schema_version").jsonPrimitive.let { !it.isString && it.int == 1 })
    require(value.getValue("action_authorized").jsonPrimitive.let { !it.isString && !it.boolean })
    val category = value.string("category", 16)
    val intent = mapOf("delivery" to "delivery_event", "transport" to "transport_event",
        "calendar" to "calendar_event", "reminder" to "reminder", "noise" to "none")[category]
    require(intent != null && intent == value.string("intent", 32))
    val priority = value.string("priority", 16)
    require(priority in listOf("low", "default", "high"))
    val entities = value.getValue("entities").jsonObject
    val subject = entities.optional("subject", 160)
    val location = entities.optional("location", 200)
    val service = entities.optional("service", 80)
    val time = value.getValue("time").jsonObject
    val source = time.optional("source", 128)
    val zoneName = time.string("timezone", 64)
    val zone = ZoneId.of(zoneName)
    val at = time.optional("at", 32)
    val date = time.optional("date", 10)
    val resolution = time.string("resolution", 16)
    require((resolution == "absent") == (source == null))
    val timeText = when (resolution) {
        "exact" -> {
            require(at != null && date == null)
            require(Regex("\\d{4}-\\d{2}-\\d{2}T(?:[01]\\d|2[0-3]):[0-5]\\d:[0-5]\\d(?:\\.\\d{1,6})?Z").matches(at))
            DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm:ss", Locale.ROOT).withZone(zone).format(Instant.parse(at))
        }
        "date_only" -> {
            require(at == null && date != null && Regex("\\d{4}-\\d{2}-\\d{2}").matches(date))
            LocalDate.parse(date).format(DateTimeFormatter.ofPattern("dd.MM.yyyy", Locale.ROOT)) + " · время не указано"
        }
        "absent", "unresolved" -> {
            require(at == null && date == null)
            if (resolution == "absent") "Время не указано" else "Точное время не определено"
        }
        else -> error("Неподдерживаемый формат")
    }
    if (category == "noise") require(priority == "low" && subject == null && location == null && service == null && resolution == "absent")
    val fields = mutableListOf(
        "Категория разбора" to coreCategory(category),
        "Приоритет разбора" to when (priority) { "low" -> "Низкий"; "high" -> "Высокий"; else -> "Обычный" },
        "Событие / дело" to (subject ?: "Не указано"), "Место" to (location ?: "Не указано"),
        "Сервис" to (service ?: "Не указан"), "Распознанное время" to timeText,
        "Часовой пояс разбора" to zoneName,
    )
    source?.let { fields.add("Время в тексте" to it) }
    return CoreProcessing.Extracted(fields)
}
