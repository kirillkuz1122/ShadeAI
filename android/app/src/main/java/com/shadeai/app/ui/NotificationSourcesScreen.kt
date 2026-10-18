package com.shadeai.app.ui

import android.content.ActivityNotFoundException
import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import com.shadeai.app.core.config.NotificationSources

@Composable
fun NotificationSourcesScreen(state: SourcesUiState, onToggle: (String, Boolean) -> Unit,
                              onRefresh: () -> Unit, onBack: () -> Unit) {
    val context = LocalContext.current
    var settingsError by remember { mutableStateOf(false) }
    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing)
            .verticalScroll(rememberScrollState()).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)) {
            OutlinedButton(onClick = onBack, colors = ButtonDefaults.outlinedButtonColors(
                contentColor = MaterialTheme.colorScheme.onSurface)) { Text("К подключению") }
            Text("Уведомления", style = MaterialTheme.typography.headlineLarge)
            Text(if (state.error != null) "Состояние доступа не проверено"
                else if (state.access) "Доступ Android выдан" else "Доступ Android не выдан",
                style = MaterialTheme.typography.titleMedium)
            Text("Android предоставляет сервису доступ ко всем уведомлениям. Shade сохраняет только выбранные ниже источники после проверки приватности.")
            Button(onClick = {
                settingsError = false
                try { context.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) }
                catch (_: ActivityNotFoundException) { settingsError = true }
            }, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) {
                Text("Настроить доступ Android")
            }
            if (settingsError) Text("Откройте настройки Android → Специальный доступ → Доступ к уведомлениям → Shade AI.")
            OutlinedButton(onClick = onRefresh, enabled = !state.busy,
                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.onSurface),
                modifier = Modifier.fillMaxWidth()) { Text("Обновить состояние") }
            if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            HorizontalDivider()
            Text("Источники", style = MaterialTheme.typography.titleLarge)
            Text("Выберите сервисы вручную. Выбор сохраняется сразу и действует после выдачи доступа. Список ограничен политикой Core; приложение может быть ещё не установлено.")
            NotificationSources.catalog.forEach { (pkg, label) ->
                Row(Modifier.fillMaxWidth().toggleable(value = pkg in state.selected,
                    enabled = !state.busy && state.error == null, role = Role.Checkbox,
                    onValueChange = { onToggle(pkg, it) }).padding(vertical = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Checkbox(checked = pkg in state.selected, onCheckedChange = null)
                    Column { Text(label); Text(pkg, style = MaterialTheme.typography.bodySmall) }
                }
            }
            Text("Банки, мессенджеры и SMS не входят в список. Уведомления с признаками кодов и паролей, служебные и сводки групп отбрасываются до локального буфера.")
            Text("При отключении источника его локальные записи удаляются. При отзыве доступа буфер очищается при следующей проверке или подключении сервиса. Уже отправленный запрос отменить задним числом нельзя.",
                style = MaterialTheme.typography.bodySmall)
            Text("Сбор без выбранных источников выключен. Состояние сохранённых уведомлений доступно в журнале.",
                style = MaterialTheme.typography.bodySmall)
        }
    }
}
