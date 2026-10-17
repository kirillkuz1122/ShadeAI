package com.shadeai.app.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.shadeai.app.ShadeApp
import com.shadeai.app.core.config.NotificationSources
import com.shadeai.app.service.NotificationAccess
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class SourcesUiState(
    val access: Boolean = false,
    val selected: Set<String> = emptySet(),
    val busy: Boolean = true,
    val error: String? = null,
)

class NotificationSourcesViewModel(application: Application) : AndroidViewModel(application) {
    private val mutable = MutableStateFlow(SourcesUiState())
    val state = mutable.asStateFlow()
    private var running = false

    fun refresh() = change { (getApplication<Application>() as ShadeApp).capture.refresh() }

    fun toggle(pkg: String, enabled: Boolean) = change {
        val context = getApplication<Application>() as ShadeApp
        val current = NotificationSources.load(context)
        context.capture.choose(if (enabled) current + pkg else current - pkg)
    }

    private fun change(action: suspend () -> Unit) {
        if (running) return
        running = true
        mutable.value = mutable.value.copy(busy = true, error = null)
        viewModelScope.launch {
            try {
                mutable.value = withContext(Dispatchers.IO) {
                    action()
                    val context = getApplication<Application>()
                    SourcesUiState(NotificationAccess.granted(context), NotificationSources.load(context), busy = false)
                }
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                mutable.value = mutable.value.copy(busy = false,
                    error = "Не удалось проверить настройки. Показан последний известный выбор; данные могли измениться. Обновите состояние.")
            } finally { running = false }
        }
    }
}
