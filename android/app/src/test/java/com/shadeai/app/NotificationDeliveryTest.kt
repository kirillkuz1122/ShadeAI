package com.shadeai.app

import com.shadeai.app.core.network.IngestResponse
import com.shadeai.app.core.network.deliveryStatus
import com.shadeai.app.core.network.toRequest
import com.shadeai.app.data.db.DeliveryStatus
import com.shadeai.app.data.db.PendingNotificationEntity
import com.shadeai.app.service.NotificationIdentity
import org.junit.Assert.*
import org.junit.Test
import java.util.UUID
import java.util.TimeZone

class NotificationDeliveryTest {
    @Test fun receiptMustExplicitlyAcknowledgeStorageOrSkip() {
        assertEquals(DeliveryStatus.SENT, IngestResponse(1, "stored").deliveryStatus())
        assertEquals(DeliveryStatus.SENT, IngestResponse(1, "duplicate").deliveryStatus())
        assertEquals(DeliveryStatus.SKIPPED, IngestResponse(null, "skipped").deliveryStatus())
        listOf(IngestResponse(null, "stored"), IngestResponse(0, "duplicate"),
            IngestResponse(1, "skipped"), IngestResponse(1, "unknown")).forEach {
            assertEquals(DeliveryStatus.FAILED, it.deliveryStatus())
        }
    }

    @Test fun requestUsesPersistedIdentityAndUtcRegardlessOfTimezone() {
        val row = PendingNotificationEntity(packageName = "ru.ozon.app.android", title = "Заказ", text = "Готов", postTime = 0)
        UUID.fromString(row.eventId)
        val previous = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("Asia/Yekaterinburg"))
            assertEquals("1970-01-01T00:00:00Z", row.toRequest().timestamp)
            assertEquals(row.toRequest(), row.copy(status = DeliveryStatus.FAILED).toRequest())
            assertNull(row.copy(eventId = null).toRequest().eventId)
            assertFalse(row.toString().contains("Готов"))
        } finally { TimeZone.setDefault(previous) }
    }

    @Test fun identityIsStableAndFramedWithoutRawTag() {
        val first = NotificationIdentity.hash("ab", "c")
        assertTrue(first.matches(Regex("[a-f0-9]{64}")))
        assertEquals(first, NotificationIdentity.hash("ab", "c"))
        assertNotEquals(first, NotificationIdentity.hash("a", "bc"))
        assertNotEquals(first, NotificationIdentity.hash("ab", "d"))
    }
}
