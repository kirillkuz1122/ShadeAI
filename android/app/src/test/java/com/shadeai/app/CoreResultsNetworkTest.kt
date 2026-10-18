package com.shadeai.app

import com.shadeai.app.core.network.ShadeApi
import com.shadeai.app.ui.CoreProcessing
import com.shadeai.app.ui.coreProcessing
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test

class CoreResultsNetworkTest {
    @Test fun protectedReadPathsAndLegacyOrUnknownResultsAreSafe() = runBlocking {
        val key = "task19-synthetic-test-key-0000000000"
        val row = """{"id":7,"app_name":"ru.ozon.app.android","title":"private-title","text":"private-text","timestamp":"2026-10-19T00:00:00Z","priority":"default","status":"stored","event_id":"11111111-1111-4111-8111-111111111111"}"""
        MockWebServer().use { server ->
            server.start()
            server.enqueue(MockResponse().setBody("""{"items":[$row],"total":41}"""))
            server.enqueue(MockResponse().setBody(row.dropLast(1) + """, "processed_data":{"processor":"llm","schema_version":99}}"""))
            val api = ShadeApi.create(server.url("/").toString(), key)
            val page = api.notifications(20,40)
            assertEquals(41, page.total)
            assertNull(page.items.first().processingStatus)
            assertSame(CoreProcessing.Missing, coreProcessing(page.items.first().processedData))
            assertFalse(page.toString().contains("private"))
            val listRequest = server.takeRequest()
            assertEquals("GET", listRequest.method)
            assertEquals("/api/v1/notifications?limit=20&offset=40", listRequest.path)
            assertEquals("Bearer $key", listRequest.getHeader("Authorization"))
            val detail = api.notification(7)
            assertSame(CoreProcessing.Unsupported, coreProcessing(detail.processedData))
            assertFalse(detail.toString().contains("private"))
            val detailRequest = server.takeRequest()
            assertEquals("/api/v1/notifications/7", detailRequest.path)
            assertEquals("Bearer $key", detailRequest.getHeader("Authorization"))
        }
    }
}
