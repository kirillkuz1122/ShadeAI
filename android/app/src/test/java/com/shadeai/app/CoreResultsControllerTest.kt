package com.shadeai.app

import com.shadeai.app.core.network.*
import com.shadeai.app.ui.*
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import okhttp3.ResponseBody.Companion.toResponseBody

class CoreResultsControllerTest {
    private fun row(id: Long = 1) = CoreNotification(id, "ru.ozon.app.android", "private-title", "private-text", "2026-10-19T00:00:00Z", "default", status = "stored")
    private fun credentials(revision: String) = ResultsCredentials(revision, "http://127.0.0.1/api/v1/", "private-test-key-only")
    private val emptyClient = object : ResultsClient {
        override suspend fun list(limit: Int, offset: Int) = CoreNotificationsPage(listOf(row()), 1)
        override suspend fun detail(id: Long) = row(id)
    }
    @Test fun pagesAndDetailsHaveSeparateQueriesAndStopClearsPayload() = runBlocking {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        val requests = mutableListOf<String>()
        val api = object : ResultsClient {
            override suspend fun list(limit: Int, offset: Int): CoreNotificationsPage {
                requests.add("list:$limit:$offset")
                return CoreNotificationsPage((offset + 1..minOf(offset + limit, 21)).map { row(it.toLong()) }, 21)
            }
            override suspend fun detail(id: Long): CoreNotification { requests.add("detail:$id"); return row(id) }
        }
        try {
            val c = CoreResultsController(scope, { credentials("r1") }, { "r1" }, { api }, 100000)
            c.start(); assertEquals(20, c.state.value.page!!.items.size)
            c.next(); assertEquals(20, c.state.value.offset)
            c.select(21); assertNull(c.state.value.page); assertEquals(21L, c.state.value.detail!!.id)
            c.select(null); c.previous(); assertEquals(0, c.state.value.offset)
            assertTrue(requests.containsAll(listOf("list:20:0", "list:20:20", "detail:21")))
            c.close(); assertNull(c.state.value.page); assertNull(c.state.value.detail)
            assertFalse(c.state.value.toString().contains("private"))
            assertFalse(credentials("r1").toString().contains("private"))
        } finally { scope.cancel() }
    }
    @Test fun lateOldServerResponseCannotOverwriteNewSettings() = runBlocking {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        val gate = CompletableDeferred<Unit>()
        var revision = "old"
        val oldApi = object : ResultsClient {
            override suspend fun list(limit: Int, offset: Int) = withContext(NonCancellable) {
                gate.await(); CoreNotificationsPage(listOf(row(99)), 1)
            }
            override suspend fun detail(id: Long) = row(id)
        }
        try {
            val c = CoreResultsController(scope, { credentials(revision) }, { revision }, { if (it.revision == "old") oldApi else emptyClient }, 100000)
            c.start(); revision = "new"; c.settingsChanged()
            assertEquals(1L, c.state.value.page!!.items.first().id)
            gate.complete(Unit); yield()
            assertEquals(1L, c.state.value.page!!.items.first().id)
            c.close()
        } finally { gate.complete(Unit); scope.cancel() }
    }
    @Test fun stopIgnoresLateNonCancellableResponse() = runBlocking {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        val gate = CompletableDeferred<Unit>()
        val api = object : ResultsClient {
            override suspend fun list(limit: Int, offset: Int) = withContext(NonCancellable) { gate.await(); CoreNotificationsPage(listOf(row()), 1) }
            override suspend fun detail(id: Long) = row(id)
        }
        try {
            val c = CoreResultsController(scope, { credentials("r1") }, { "r1" }, { api }, 100000)
            c.start(); c.close(); gate.complete(Unit); yield()
            assertNull(c.state.value.page); assertNull(c.state.value.detail)
        } finally { gate.complete(Unit); scope.cancel() }
    }
    @Test fun unauthorizedAndNotFoundClearOldDataWithoutRawError() = runBlocking {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        var failure: Int? = null
        val api = object : ResultsClient {
            override suspend fun list(limit: Int, offset: Int): CoreNotificationsPage {
                failure?.let { throw HttpException(Response.error<CoreNotificationsPage>(it, "private-error-body".toResponseBody())) }
                return CoreNotificationsPage(listOf(row()), 1)
            }
            override suspend fun detail(id: Long) = row(id)
        }
        try {
            val c = CoreResultsController(scope, { credentials("r1") }, { "r1" }, { api }, 100000)
            c.start(); assertNotNull(c.state.value.page)
            for (code in listOf(401,404)) {
                failure = code; c.refresh()
                assertNull(c.state.value.page); assertNull(c.state.value.detail)
                assertNotNull(c.state.value.error); assertFalse(c.state.value.error!!.contains("private"))
            }
            c.close()
        } finally { scope.cancel() }
    }
}
