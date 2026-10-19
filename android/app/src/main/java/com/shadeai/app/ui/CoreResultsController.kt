package com.shadeai.app.ui

import com.shadeai.app.core.network.CoreNotification
import com.shadeai.app.core.network.CoreNotificationsPage
import com.shadeai.app.core.network.ResultsClient
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import retrofit2.HttpException

class ResultsCredentials(val revision: String, val baseUrl: String, val apiKey: String) {
    override fun toString() = "ResultsCredentials(redacted)"
}

data class CoreResultsState(
    val offset: Int = 0,
    val selectedId: Long? = null,
    val page: CoreNotificationsPage? = null,
    val detail: CoreNotification? = null,
    val loading: Boolean = true,
    val error: String? = null,
) {
    override fun toString() = "CoreResultsState(redacted)"
}

class CoreResultsController(
    private val scope: CoroutineScope,
    private val credentials: suspend () -> ResultsCredentials,
    private val currentRevision: () -> String,
    private val createClient: (ResultsCredentials) -> ResultsClient,
    private val pollMillis: Long = 5000,
) {
    private val mutable = MutableStateFlow(CoreResultsState())
    val state = mutable.asStateFlow()
    private var request: Job? = null
    private var generation = 0
    private var active = false
    private var sessionRevision: String? = null

    fun start() { active = true; refresh() }
    fun close() {
        active = false
        generation++
        request?.cancel(); request = null
        mutable.value = mutable.value.copy(page = null, detail = null, loading = true, error = null)
    }
    fun settingsChanged() {
        sessionRevision = null
        mutable.value = CoreResultsState()
        if (active) refresh()
    }
    fun select(id: Long?) {
        if (id != null && id <= 0) return
        mutable.value = mutable.value.copy(selectedId = id)
        refresh()
    }
    fun next() {
        val state = mutable.value
        if (state.loading || state.page == null || state.offset + 20 >= state.page.total) return
        mutable.value = CoreResultsState(offset = state.offset + 20)
        refresh()
    }
    fun previous() {
        val state = mutable.value
        if (state.loading || state.offset == 0) return
        mutable.value = CoreResultsState(offset = (state.offset - 20).coerceAtLeast(0))
        refresh()
    }
    fun refresh() {
        if (!active) return
        request?.cancel()
        val token = ++generation
        val query = mutable.value
        mutable.value = query.copy(page = null, detail = null, loading = true, error = null)
        request = scope.launch {
            try {
                val snapshot = credentials()
                if (!valid(token, snapshot.revision)) return@launch
                if (sessionRevision != null && sessionRevision != snapshot.revision) {
                    sessionRevision = snapshot.revision
                    mutable.value = CoreResultsState()
                    refresh()
                    return@launch
                }
                sessionRevision = snapshot.revision
                require(snapshot.apiKey.isNotBlank())
                val api = createClient(snapshot)
                while (isActive && valid(token, snapshot.revision)) {
                    try {
                        val page = if (query.selectedId == null) api.list(20, query.offset) else null
                        val detail = query.selectedId?.let { api.detail(it) }
                        if (!valid(token, snapshot.revision)) return@launch
                        check(page == null || (page.items.size <= 20 && page.total >= 0 && page.items.all { it.id > 0 }))
                        check(detail == null || detail.id == query.selectedId)
                        if (page != null && page.items.isEmpty() && query.offset > 0 && page.total <= query.offset) {
                            mutable.value = CoreResultsState()
                            refresh()
                            return@launch
                        }
                        mutable.value = query.copy(page = page, detail = detail, loading = false)
                    } catch (error: CancellationException) { throw error
                    } catch (error: Exception) {
                        if (!valid(token, snapshot.revision)) return@launch
                        mutable.value = query.copy(page = null, detail = null, loading = false, error = networkError(error))
                        if (error is HttpException && error.code() in listOf(401, 403, 404)) return@launch
                    }
                    delay(pollMillis)
                }
            } catch (error: CancellationException) { throw error
            } catch (_: Exception) {
                if (token == generation && active) mutable.value = query.copy(page = null, detail = null,
                    loading = false, error = "Проверьте сохранённый адрес и ключ Core в подключении.")
            }
        }
    }
    private fun valid(token: Int, revision: String) =
        active && token == generation && revision == currentRevision()

    private fun networkError(error: Exception) = when ((error as? HttpException)?.code()) {
        401, 403 -> "Ключ не принят. Проверьте подключение к Core."
        404 -> "Запись уже удалена или срок хранения истёк."
        else -> "Не удалось получить результаты Core. Проверьте локальную сеть и повторите обновление."
    }
}
