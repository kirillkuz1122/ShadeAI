package com.shadeai.app

import com.shadeai.app.core.config.AddressException
import com.shadeai.app.core.config.ServerAddress
import com.shadeai.app.core.network.MissingCredentialsException
import com.shadeai.app.core.network.ShadeApi
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import retrofit2.HttpException

class ConnectionTest {
    private val key = "task09-synthetic-key-0000000000000"

    @Test fun normalizeRootAndApiPath() {
        assertEquals("http://127.0.0.1:8000/api/v1/", ServerAddress.normalize(" http://127.0.0.1:8000 "))
        assertEquals("https://shade.local/api/v1/", ServerAddress.normalize("https://SHADE.local/api/v1"))
    }

    @Test fun rejectUnsafeAddresses() {
        for (url in listOf("", "shade.local", "file:///tmp/key", "http://user:secret@shade.local", "http://shade.local/?key=secret", "http://shade.local/#secret", "http://shade.local/other", "http://sha de.local")) {
            assertThrows(AddressException::class.java) { ServerAddress.normalize(url) }
        }
        assertThrows(AddressException::class.java) { ServerAddress.normalize("http://other.local") { false } }
        assertEquals("https://other.local/api/v1/", ServerAddress.normalize("https://other.local") { false })
    }

    @Test fun keyHasSafeHeaderCharacters() {
        assertTrue(ServerAddress.validKey(key))
        assertFalse(ServerAddress.validKey("short"))
        assertFalse(ServerAddress.validKey(key + "\r\n"))
        assertFalse(ServerAddress.validKey(key + "я"))
        assertFalse(ServerAddress.validKey(key + " "))
        assertThrows(IllegalArgumentException::class.java) {
            ShadeApi.create("http://127.0.0.1", key + "\r\n")
        }
    }

    @Test fun healthNeverCarriesKeyAndProtectedRequestDoes() = runBlocking {
        MockWebServer().use { server ->
            server.start()
            server.enqueue(MockResponse().setBody("""{"status":"degraded","uptime":1,"ha_connected":false,"llm_status":"not_loaded","db_size":"0 MB"}"""))
            server.enqueue(MockResponse().setBody("""{"items":[],"total":0}"""))
            val api = ShadeApi.create(server.url("/").toString(), key)
            assertEquals("degraded", api.health().status)
            assertNull(server.takeRequest().getHeader("Authorization"))
            assertEquals(0L, api.verifyAccess().total)
            val protected = server.takeRequest()
            assertEquals(0, protected.sequenceNumber)
            assertEquals("Bearer $key", protected.getHeader("Authorization"))
            assertEquals("/api/v1/notifications?limit=1", protected.path)
        }
    }

    @Test fun missingKeySendsNothing() = runBlocking {
        MockWebServer().use { server ->
            server.start()
            try { ShadeApi.create(server.url("/").toString(), "").verifyAccess(); fail("Без ключа запрос не должен отправляться") }
            catch (_: MissingCredentialsException) { }
            assertEquals(0, server.requestCount)
        }
    }

    @Test fun redirectDoesNotForwardKey() = runBlocking {
        MockWebServer().use { first -> MockWebServer().use { second ->
            first.start(); second.start()
            first.enqueue(MockResponse().setResponseCode(302).addHeader("Location", second.url("/api/v1/notifications")))
            try { ShadeApi.create(first.url("/").toString(), key).verifyAccess(); fail("Redirect должен быть отклонён") }
            catch (error: HttpException) { assertEquals(302, error.code()) }
            assertEquals(1, first.requestCount)
            assertEquals(0, second.requestCount)
        } }
    }

    @Test fun unauthorizedIsNotRetried() = runBlocking {
        MockWebServer().use { server ->
            server.start(); server.enqueue(MockResponse().setResponseCode(401))
            try { ShadeApi.create(server.url("/").toString(), key).verifyAccess(); fail("Ключ должен быть отклонён") }
            catch (error: HttpException) { assertEquals(401, error.code()) }
            assertEquals(1, server.requestCount)
        }
    }
}
