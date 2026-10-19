package com.shadeai.app.ui

import com.shadeai.app.core.network.CoreRule
import java.time.ZoneId

fun allowedLight(value: String) = value.length <= 255 && Regex("light\\.[a-z0-9_]+").matches(value)
fun knownRule(row: CoreRule): Boolean = try {
    val t=row.trigger; val e=row.evidence
    Regex("aut_[0-9a-f]{32}").matches(row.id) && row.version > 0 && row.name.isNotBlank() && row.name.length <= 200 &&
        row.status in listOf("pending","accepted","rejected","disabled","needs_review") &&
        row.confidence.isFinite() && row.confidence in 0.0..1.0 && t.type == "presence_transition" &&
        t.kind in listOf("arrival_home","departure_home") &&
        Regex("binary_sensor\\.[a-z0-9_]+").matches(t.entityId) &&
        t.fromState == (if(t.kind == "arrival_home") "off" else "on") &&
        t.toState == (if(t.kind == "arrival_home") "on" else "off") &&
        t.dayGroup in listOf("weekdays","weekends") && ZoneId.of(t.timezone) != null &&
        listOf(t.windowStart,t.windowEnd).all { Regex("(?:[01]\\d|2[0-3]):[0-5]\\d").matches(it) } &&
        e.eligibleDays in 1..30 && e.supportDays in 0..e.eligibleDays && e.dispersion.isFinite() && e.dispersion in 0.0..45.0 &&
        (row.action == null || (allowedLight(row.action.entityId) && row.action.params.isEmpty() &&
            row.action.service == if(t.kind == "arrival_home") "turn_on" else "turn_off"))
} catch (_: Exception) { false }

fun ruleStatus(value: String) = when(value) {
    "pending" -> "Предложение"; "accepted" -> "Принято"; "rejected" -> "Отклонено"
    "disabled" -> "Выключено"; "needs_review" -> "Требуется новое решение"
    else -> "Формат не поддерживается"
}
fun decisionLabel(value: String) = when(value) {
    "accept" -> "Принято пользователем"; "reject" -> "Отклонено пользователем"
    "disable" -> "Выключено пользователем"; "suggested" -> "Предложено"
    "source_changed" -> "Условия изменились"; "evidence_updated" -> "Обновлена статистика"
    "approval_invalidated" -> "Нужно новое подтверждение"; "source_unavailable" -> "Источник недоступен"
    else -> "Служебное изменение"
}
