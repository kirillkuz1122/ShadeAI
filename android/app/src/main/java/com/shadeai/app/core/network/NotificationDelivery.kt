package com.shadeai.app.core.network

import com.shadeai.app.data.db.DeliveryStatus
import com.shadeai.app.data.db.PendingNotificationEntity
import java.time.Instant

fun PendingNotificationEntity.toRequest() = NotificationIngest(
    appName = packageName, title = title, text = text,
    timestamp = Instant.ofEpochMilli(postTime).toString(), eventId = eventId,
)

fun IngestResponse.deliveryStatus(): DeliveryStatus = when {
    status in setOf("stored", "duplicate") && id != null && id > 0 -> DeliveryStatus.SENT
    status == "skipped" && id == null -> DeliveryStatus.SKIPPED
    else -> DeliveryStatus.FAILED
}

// Только безопасные категории; исключения Retrofit/ответы Core не сохраняем.
class DeliveryFailure(val category: String, val pause: Boolean = false, val permanent: Boolean = false) : Exception("Delivery failed")

suspend fun sendNotification(api: ShadeApi, item: PendingNotificationEntity): DeliveryStatus = try {
    val status = api.ingest(item.toRequest()).deliveryStatus()
    if (status == DeliveryStatus.FAILED) throw DeliveryFailure("receipt", pause = true)
    status
} catch (error: retrofit2.HttpException) {
    val code = error.code()
    throw DeliveryFailure("http_$code", pause = code in 300..499 && code !in setOf(400, 409, 413, 422, 408, 425, 429),
        permanent = code in setOf(400, 409, 413, 422))
} catch (_: kotlinx.serialization.SerializationException) {
    throw DeliveryFailure("receipt", pause = true)
} catch (_: javax.net.ssl.SSLException) {
    throw DeliveryFailure("tls", pause = true)
} catch (_: IllegalArgumentException) {
    throw DeliveryFailure("configuration", pause = true)
}
