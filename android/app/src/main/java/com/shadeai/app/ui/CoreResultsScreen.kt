package com.shadeai.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.shadeai.app.core.config.NotificationSources
import com.shadeai.app.core.network.CoreNotification
import java.time.Instant

@Composable
fun CoreResultsRoute(model: CoreResultsViewModel, onBack: () -> Unit) {
    val state by model.state.collectAsStateWithLifecycle()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(model, lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> model.start()
                Lifecycle.Event.ON_STOP -> model.close()
                else -> Unit
            }
        }
        lifecycle.addObserver(observer)
        if (lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) model.start()
        onDispose { lifecycle.removeObserver(observer); model.close() }
    }
    BackHandler(state.selectedId != null) { model.select(null) }
    CoreResultsScreen(state, model::select, model::next, model::previous, model::refresh, onBack)
}

private fun resultStatus(row: CoreNotification) = when (row.processingStatus ?: row.status) {
    "pending", "stored" -> "Ожидает разбора"
    "processing" -> "Обрабатывается"
    "processed" -> "Обработано Core"
    "failed" -> "Ошибка обработки"
    else -> "Состояние не поддерживается"
}
private fun eventTime(value: String): String = try {
    journalTime(Instant.parse(value).toEpochMilli())
} catch (_: Exception) { "Время неизвестно" }

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CoreResultsScreen(state: CoreResultsState, select: (Long?) -> Unit, next: () -> Unit,
                      previous: () -> Unit, refresh: () -> Unit, onBack: () -> Unit) {
    val colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.onSurface)
    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        LazyColumn(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing),
            contentPadding = PaddingValues(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            item {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = onBack, colors = colors) { Text("К подключению") }
                    if (state.selectedId != null) OutlinedButton(onClick = { select(null) }, colors = colors) {
                        Text("К списку результатов")
                    }
                }
            }
            item {
                Text("Результаты Core", style = MaterialTheme.typography.headlineLarge)
                Text("Сохранённые записи текущего сервера. Доставка в Core и успешный разбор — разные состояния.")
                OutlinedButton(onClick = refresh, colors = colors, enabled = !state.loading) { Text("Обновить результаты") }
                if (state.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
                state.error?.let { Text(it, Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
            }
            if (state.selectedId == null) {
                val page = state.page
                if (page != null) {
                    item { Text("Всего: ${page.total} · Страница ${state.offset / 20 + 1}") }
                    if (page.items.isEmpty()) item { Text("В Core пока нет сохранённых уведомлений.") }
                    items(page.items, key = { it.id }) { row ->
                        OutlinedCard(onClick = { select(row.id) }, modifier = Modifier.fillMaxWidth(),
                            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
                            colors = CardDefaults.outlinedCardColors(containerColor = MaterialTheme.colorScheme.surface,
                                contentColor = MaterialTheme.colorScheme.onSurface)) {
                            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text(NotificationSources.catalog[row.appName] ?: row.appName, style = MaterialTheme.typography.labelMedium)
                                Text(row.title.ifBlank { "Без заголовка" }, style = MaterialTheme.typography.titleMedium)
                                Text(resultStatus(row))
                                Text(eventTime(row.timestamp), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                    item {
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(onClick = previous, colors = colors, enabled = state.offset > 0 && !state.loading) { Text("Более новые") }
                            OutlinedButton(onClick = next, colors = colors, enabled = state.offset + 20 < page.total && !state.loading) { Text("Более ранние") }
                        }
                    }
                }
            } else state.detail?.let { row ->
                item {
                    Text(row.title.ifBlank { "Без заголовка" }, style = MaterialTheme.typography.headlineSmall)
                    Text(row.text)
                    Text("Core #${row.id} · ${resultStatus(row)}")
                    Text("UUID: ${row.eventId ?: "Старая запись без UUID"}")
                    Text("Уведомление: ${eventTime(row.timestamp)}")
                    Text("Попыток: ${row.processingAttempts}")
                    coreProcessingError(row.processingErrorCode)?.let { Text(it) }
                    when (val result = coreProcessing(row.processedData)) {
                        CoreProcessing.Missing -> Text("Результат разбора ещё не получен.")
                        CoreProcessing.Diagnostic -> Text("Проверен конвейер очереди. Анализ текста и LLM не выполнялись.")
                        CoreProcessing.Unsupported -> Text("Формат результата не поддерживается. Проверьте версию клиента и Core.")
                        is CoreProcessing.Extracted -> Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            Text("Локальный разбор", style = MaterialTheme.typography.titleLarge)
                            result.fields.forEach { (label, value) ->
                                Column { Text(label, style = MaterialTheme.typography.labelMedium); Text(value) }
                            }
                            Text("Модель может ошибаться. Результат описывает уведомление и не разрешает управление устройствами.")
                        }
                    }
                }
            }
            item { Text("Это история Core. Локальный журнал Android показывает только буфер доставки.", style = MaterialTheme.typography.bodySmall) }
        }
    }
}
