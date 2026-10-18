package com.shadeai.app.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.shadeai.app.ShadeApp
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.data.db.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class JournalUiState(
    val query: JournalQuery = JournalQuery(),
    val snapshot: JournalSnapshot? = null,
    val page: Int = 1,
    val loading: Boolean = true,
    val error: String? = null,
) {
    override fun toString() = "JournalUiState(redacted)"
}

class JournalViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as ShadeApp
    private val journal = NotificationJournal(app.database) { ServerPrefs.revision(app) }
    private val mutable = MutableStateFlow(JournalUiState())
    val state = mutable.asStateFlow()
    private val cursors = mutableListOf<Long?>(null)
    private var observation: Job? = null

    fun filter(filter: JournalFilter) {
        cursors.clear(); cursors.add(null)
        observe(JournalQuery(filter))
    }

    fun next() {
        val current = mutable.value
        val snapshot = current.snapshot ?: return
        if (!snapshot.hasMore || current.loading) return
        val cursor = snapshot.rows.lastOrNull()?.id ?: return
        cursors.add(cursor)
        observe(current.query.copy(beforeId = cursor))
    }

    fun previous() {
        if (cursors.size <= 1) return
        cursors.removeAt(cursors.lastIndex)
        observe(mutable.value.query.copy(beforeId = cursors.last()))
    }

    fun refresh() = observe(mutable.value.query)

    fun close() {
        observation?.cancel(); observation = null
        mutable.value = mutable.value.copy(snapshot = null, loading = true, error = null)
    }

    private fun observe(query: JournalQuery) {
        observation?.cancel()
        mutable.value = JournalUiState(query, page = cursors.size)
        observation = viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { app.capture.refresh() }
                journal.observe(query).collect { snapshot ->
                    if (snapshot.rows.isEmpty() && cursors.size > 1) {
                        filter(query.filter)
                    } else mutable.value = JournalUiState(query, snapshot, cursors.size, loading = false)
                }
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                mutable.value = JournalUiState(query, page = cursors.size, loading = false,
                    error = "Не удалось прочитать локальный журнал. Повторите обновление.")
            }
        }
    }
}
