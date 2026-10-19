package com.shadeai.app.ui

import com.shadeai.app.core.network.CoreAccess
import com.shadeai.app.core.network.CoreAccessGrant
import java.time.Duration
import java.time.Instant
import java.util.UUID

private val accessStates = setOf("active", "dispatching", "used", "failed", "unknown", "revoked", "expired")
private fun accessLock(value: String) = Regex("lock\\.[a-z0-9_]{1,249}").matches(value)
private fun accessHash(value: String) = Regex("[a-f0-9]{64}").matches(value)

fun knownAccessGrant(value: CoreAccessGrant, allowPin: Boolean = false): Boolean = runCatching {
    val id = UUID.fromString(value.id)
    val start = Instant.parse(value.createdAt)
    val end = Instant.parse(value.expiresAt)
    id.version() == 4 && id.toString() == value.id && value.notificationId > 0 &&
        accessLock(value.entityId) && accessHash(value.policyScope) &&
        value.durationMinutes in 1..15 && value.state in accessStates &&
        Duration.between(start, end) == Duration.ofMinutes(value.durationMinutes.toLong()) &&
        Instant.parse(value.updatedAt) != null &&
        (value.pin == null || allowPin && value.state == "active" && Regex("[0-9]{6}").matches(value.pin)) &&
        (value.newState == null || value.newState in setOf("locked", "unlocked", "locking", "unlocking", "open", "opening", "jammed", "unknown", "unavailable"))
}.getOrDefault(false)

fun knownAccess(value: CoreAccess): Boolean = value.version == 1 && value.adapter == "shade_keypad" &&
    accessHash(value.policyScope) && value.maxMinutes == 15 && value.oneUse && value.ownerConfirmation &&
    value.allowedLocks.size <= 5 && value.allowedLocks.all(::accessLock) &&
    value.allowedLocks.distinct().size == value.allowedLocks.size &&
    value.grants.size <= 50 && value.grants.all { knownAccessGrant(it) } &&
    value.grants.map { it.id }.distinct().size == value.grants.size

fun accessStatus(value: String) = when (value) {
    "active" -> "Код действует до указанного срока"
    "dispatching" -> "Команда отправляется. Отзыв уже не гарантирован"
    "used" -> "Код использован; Home Assistant принял unlock"
    "failed" -> "Команда не отправлена или отклонена; код уже потреблён"
    "unknown" -> "Результат неизвестен. Проверьте дверь вручную"
    "revoked" -> "Код отозван"
    "expired" -> "Срок кода истёк"
    else -> "Неподдерживаемое состояние"
}
