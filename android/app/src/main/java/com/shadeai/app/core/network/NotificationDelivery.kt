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
