package com.shadeai.app

import com.shadeai.app.core.network.DeliveryFailure
import com.shadeai.app.core.network.ShadeApi
import com.shadeai.app.core.network.sendNotification
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
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

    @Test fun httpFailuresHaveSafeCategoriesAndCorrectRetryPolicy() = runBlocking {
        val server = MockWebServer()
        server.start()
        try {
            val api = ShadeApi.create(server.url("/api/v1/").toString(), "synthetic-key-000000000000000000000000")
            val row = PendingNotificationEntity(packageName = "ru.ozon.app.android", title = "Заказ", text = "Готов", postTime = 1)
            for (code in listOf(401, 403, 302, 404, 400, 409, 413, 422, 408, 425, 429, 500, 503)) {
                server.enqueue(MockResponse().setResponseCode(code).setBody("private-response-must-not-be-saved"))
                try { sendNotification(api, row); fail("HTTP $code должен быть ошибкой") }
                catch (error: DeliveryFailure) {
                    assertEquals("http_$code", error.category)
                    assertEquals(code in setOf(401, 403, 302, 404), error.pause)
                    assertEquals(code in setOf(400, 409, 413, 422), error.permanent)
                    assertFalse(error.toString().contains("private-response"))
                }
            }
        } finally { server.shutdown() }
    }

    @Test fun malformedOrUnacknowledgedResponsePausesInsteadOfMarkingSent() = runBlocking {
        val server = MockWebServer(); server.start()
        try {
            val api = ShadeApi.create(server.url("/api/v1/").toString(), "synthetic-key-000000000000000000000000")
            val row = PendingNotificationEntity(packageName = "ru.ozon.app.android", title = "Заказ", text = "Готов", postTime = 1)
            for (body in listOf("invalid-json", "{\"status\":\"stored\"}", "{\"id\":0,\"status\":\"duplicate\"}")) {
                server.enqueue(MockResponse().setBody(body))
                try { sendNotification(api, row); fail("Нужно подтверждение") }
                catch (error: DeliveryFailure) { assertEquals("receipt", error.category); assertTrue(error.pause) }
            }
        } finally { server.shutdown() }
    }

    @Test fun identityIsStableAndFramedWithoutRawTag() {
        val first = NotificationIdentity.hash("ab", "c")
        assertTrue(first.matches(Regex("[a-f0-9]{64}")))
        assertEquals(first, NotificationIdentity.hash("ab", "c"))
        assertNotEquals(first, NotificationIdentity.hash("a", "bc"))
        assertNotEquals(first, NotificationIdentity.hash("ab", "d"))
    }
}
