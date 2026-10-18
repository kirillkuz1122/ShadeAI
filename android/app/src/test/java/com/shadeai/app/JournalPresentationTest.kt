package com.shadeai.app

import com.shadeai.app.data.db.*
import com.shadeai.app.ui.deliveryError
import com.shadeai.app.ui.deliveryLabel
import com.shadeai.app.ui.queueMessage
import org.junit.Assert.*
import org.junit.Test

class JournalPresentationTest {
    private fun snapshot(control: DeliveryControl? = null, revision: String = "current", queued: Int = 1) =
        JournalSnapshot(emptyList(), mapOf(DeliveryStatus.PENDING to queued), false, control, null, revision)

    @Test fun deliveryStatusesHaveDistinctHumanLabels() {
        assertEquals(5, DeliveryStatus.entries.map(::deliveryLabel).toSet().size)
        assertEquals("Получено Core", deliveryLabel(DeliveryStatus.SENT))
        assertEquals("Не подтверждено", deliveryLabel(DeliveryStatus.FAILED))
        assertEquals("Отклонено Core", deliveryLabel(DeliveryStatus.REJECTED))
    }

    @Test fun errorMappingNeverEchoesUnknownStoredText() {
        assertNull(deliveryError(null))
        assertTrue(deliveryError("http_401")!!.contains("Ключ Core не принят"))
        assertTrue(deliveryError("http_422")!!.contains("Автоматического повтора нет"))
        assertTrue(deliveryError("http_503")!!.contains("503"))
        for (raw in listOf("raw-private-message", "http_503 secret", "network\nprivate", "http_0")) {
            assertFalse(deliveryError(raw)!!.contains(raw))
        }
    }

    @Test fun queueUsesCurrentRevisionAndDoesNotClaimConnectivityOrDelivery() {
        assertEquals("Очередь пуста", queueMessage(snapshot(queued = 0)))
        assertTrue(queueMessage(snapshot(DeliveryControl(revision = "current", blocked = true))).contains("приостановлена"))
        assertFalse(queueMessage(snapshot(DeliveryControl(revision = "old", blocked = true))).contains("приостановлена"))
        assertTrue(queueMessage(snapshot(DeliveryControl(revision = "current", nextAttemptAt = 2000)), now = 1000).startsWith("Повтор не раньше"))
        assertTrue(queueMessage(snapshot(DeliveryControl(revision = "current", nextAttemptAt = 1000)), now = 2000).startsWith("Очередь ожидает"))
    }
}
