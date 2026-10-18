package com.shadeai.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.shadeai.app.core.config.NotificationSources
import com.shadeai.app.data.db.*

@Composable
fun JournalRoute(model: JournalViewModel, onBack: () -> Unit, onSources: () -> Unit) {
    val state by model.state.collectAsStateWithLifecycle()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(model, lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> model.refresh()
                Lifecycle.Event.ON_STOP -> model.close()
                else -> Unit
            }
        }
        lifecycle.addObserver(observer)
        if (lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) model.refresh()
        onDispose { lifecycle.removeObserver(observer); model.close() }
    }
    JournalScreen(state, model::filter, model::next, model::previous, model::refresh, onBack, onSources)
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun JournalScreen(state: JournalUiState, onFilter: (JournalFilter) -> Unit,
                  onNext: () -> Unit, onPrevious: () -> Unit, onRefresh: () -> Unit,
                  onBack: () -> Unit, onSources: () -> Unit) {
    val snapshot = state.snapshot
    val rows = snapshot?.rows.orEmpty()
    val scroll = rememberLazyListState()
    var detailId by rememberSaveable { mutableStateOf<Long?>(null) }
    LaunchedEffect(state.query) { detailId = null; scroll.scrollToItem(0) }
    val outline = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.onSurface)
    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        LazyColumn(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing), state = scroll,
            contentPadding = PaddingValues(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            item {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = onBack, colors = outline) { Text("К подключению") }
                    OutlinedButton(onClick = onSources, colors = outline) { Text("Источники") }
                }
            }
            item {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("НА ЭТОМ УСТРОЙСТВЕ", style = MaterialTheme.typography.labelMedium)
                    Text("Журнал уведомлений", style = MaterialTheme.typography.headlineLarge)
                    Text("Локальные записи и состояние доставки в Core.", style = MaterialTheme.typography.bodyMedium)
                }
            }
            item {
                if (snapshot != null) Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("В буфере: ${snapshot.total} · В очереди: ${snapshot.queued}",
                        style = MaterialTheme.typography.titleMedium)
                    Text(queueMessage(snapshot), Modifier.semantics { liveRegion = LiveRegionMode.Polite })
                    if (snapshot.control?.blocked == true && snapshot.control.revision == snapshot.revision) {
                        deliveryError(snapshot.firstUnsent?.lastError)?.let { Text(it) }
                    }
                }
            }
            item {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    JournalFilter.entries.forEach { filter ->
                        FilterChip(selected = state.query.filter == filter, onClick = { onFilter(filter) },
                            label = { Text(filter.label) },
                            colors = FilterChipDefaults.filterChipColors(labelColor = MaterialTheme.colorScheme.onSurface,
                                selectedContainerColor = MaterialTheme.colorScheme.primary,
                                selectedLabelColor = MaterialTheme.colorScheme.onPrimary))
                    }
                }
            }
            item {
                OutlinedButton(onClick = onRefresh, colors = outline, enabled = !state.loading) { Text("Обновить журнал") }
                if (state.loading) LinearProgressIndicator(Modifier.fillMaxWidth(),
                    color = MaterialTheme.colorScheme.onSurface,
                    trackColor = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.12f))
                state.error?.let { Text(it, Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
                if (snapshot != null) Text("${state.query.filter.label}: ${snapshot.count(state.query.filter)} · Страница ${state.page}",
                    style = MaterialTheme.typography.bodySmall)
                if (snapshot != null && (state.page > 1 || snapshot.hasMore)) {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick = onPrevious, colors = outline, enabled = state.page > 1 && !state.loading) {
                            Text("Более новые")
                        }
                        OutlinedButton(onClick = onNext, colors = outline, enabled = snapshot.hasMore && !state.loading) {
                            Text("Более ранние")
                        }
                    }
                }
            }
            if (!state.loading && state.error == null && rows.isEmpty()) item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(if (snapshot?.total == 0) "Здесь пока нет записей" else "Таких записей пока нет",
                        style = MaterialTheme.typography.titleLarge)
                    Text(if (snapshot?.total == 0)
                        "Разрешите доступ Android и выберите источники. Пропущенные до сохранения уведомления в журнал не попадают."
                        else "Выберите другой фильтр или дождитесь новых уведомлений.")
                }
            }
            items(rows, key = { it.id }) { row ->
                OutlinedCard(onClick = { detailId = row.id }, modifier = Modifier.fillMaxWidth(),
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
                    colors = CardDefaults.outlinedCardColors(containerColor = MaterialTheme.colorScheme.surface,
                        contentColor = MaterialTheme.colorScheme.onSurface)) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(NotificationSources.catalog[row.packageName] ?: row.packageName,
                            style = MaterialTheme.typography.labelLarge)
                        Text(journalTime(row.postTime), style = MaterialTheme.typography.bodySmall)
                        Text(deliveryLabel(row.status), style = MaterialTheme.typography.titleSmall)
                        Text(row.title.ifBlank { "Уведомление без заголовка" }, style = MaterialTheme.typography.titleMedium,
                            maxLines = 2, overflow = TextOverflow.Ellipsis)
                        if (row.text.isNotBlank()) Text(row.text, maxLines = 3, overflow = TextOverflow.Ellipsis)
                        deliveryError(row.lastError)?.let { Text("Последняя ошибка: $it", style = MaterialTheme.typography.bodySmall) }
                    }
                }
            }
            item {
                HorizontalDivider(color = MaterialTheme.colorScheme.outline)
                Text("Неподтверждённое хранится до 7 дней, завершённое — до суток. Выключение источника удаляет его локальную историю. Core хранит свою копию отдельно.",
                    style = MaterialTheme.typography.bodySmall)
            }
        }
    }
    rows.firstOrNull { it.id == detailId }?.let { row ->
        AlertDialog(onDismissRequest = { detailId = null },
            title = { Text("Запись #${row.id}") },
            text = {
                Column(Modifier.heightIn(max = 440.dp).verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(NotificationSources.catalog[row.packageName] ?: row.packageName)
                    Text(deliveryLabel(row.status), style = MaterialTheme.typography.titleMedium)
                    Text(row.title.ifBlank { "Уведомление без заголовка" }, style = MaterialTheme.typography.titleMedium)
                    if (row.text.isNotBlank()) Text(row.text)
                    Text("Уведомление: ${journalTime(row.postTime)}")
                    Text("Сохранено: ${journalTime(row.createdAt)}")
                    row.completedAt?.let { Text("Завершено: ${journalTime(it)}") }
                    Text("Завершённых попыток: ${row.attempts}")
                    deliveryError(row.lastError)?.let { Text("Последняя ошибка: $it") }
                    Text(if (row.eventId == null) "Старая запись без UUID; повтор определяется Core по содержимому."
                        else "UUID: ${row.eventId}", style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = { TextButton(onClick = { detailId = null },
                colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.onSurface)) { Text("Закрыть запись") } },
            containerColor = MaterialTheme.colorScheme.surface, textContentColor = MaterialTheme.colorScheme.onSurface)
    }
}
