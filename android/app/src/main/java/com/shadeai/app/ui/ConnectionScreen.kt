package com.shadeai.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp

@Composable
fun ConnectionScreen(
    state: ConnectionUiState, onUrl: (String) -> Unit, onKey: (String) -> Unit,
    onCheck: () -> Unit, onClear: () -> Unit, onTest: () -> Unit,
    onSources: () -> Unit,
) {
    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(
            Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing)
                .verticalScroll(rememberScrollState()).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text("Shade AI", style = MaterialTheme.typography.headlineLarge)
            Text("Подключение к домашнему Core", style = MaterialTheme.typography.titleMedium)
            Text("Zero Cloud · данные остаются в локальной сети", style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = onSources, modifier = Modifier.fillMaxWidth()) {
                Text("Уведомления и источники")
            }
            HorizontalDivider()
            OutlinedTextField(
                value = state.url, onValueChange = onUrl, label = { Text("Адрес Shade Core") },
                modifier = Modifier.fillMaxWidth(), singleLine = true, enabled = !state.loading,
                isError = state.addressError != null, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                supportingText = { Text(state.addressError ?: "Например: http://192.168.1.100:8000/api/v1/") },
            )
            OutlinedTextField(
                value = state.keyInput, onValueChange = onKey, label = { Text("API-ключ Core") },
                modifier = Modifier.fillMaxWidth(), singleLine = true, enabled = !state.loading,
                isError = state.keyError != null, visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                supportingText = { Text(state.keyError ?: if (state.keySaved)
                    "Ключ сохранён. Пустое поле оставит его для прежнего адреса."
                    else "Введите SHADE_API_KEY из локальных настроек Core") },
            )
            Button(onClick = onCheck, enabled = !state.loading && !state.busy, modifier = Modifier.fillMaxWidth()) {
                Text("Сохранить и проверить")
            }
            OutlinedButton(onClick = onClear, enabled = !state.loading && !state.busy, modifier = Modifier.fillMaxWidth()) {
                Text("Удалить ключ")
            }
            if (state.loading || state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (state.message.isNotEmpty()) Text(state.message,
                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                style = MaterialTheme.typography.bodyMedium)
            Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surface,
                contentColor = MaterialTheme.colorScheme.onSurface,
            )) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("Состояние подключения", style = MaterialTheme.typography.titleMedium)
                    StatusRow("Core", state.coreMessage)
                    StatusRow("Авторизация", state.accessMessage)
                    StatusRow("База данных", state.health?.let { if (it.dbConnected) "Доступна" else "Недоступна" } ?: "Не проверено")
                    StatusRow("Home Assistant", state.health?.let {
                        if (it.haConnected) "Подключён" else when (it.haStatus) {
                            "HA_NOT_CONFIGURED" -> "Не настроен"
                            "HA_AUTH_FAILED" -> "Токен HA не принят"
                            "HA_TIMEOUT" -> "Время ожидания HA истекло"
                            else -> "Недоступен"
                        }
                    } ?: "Не проверено")
                    Text("Отказ Home Assistant не мешает передавать уведомления в Core.", style = MaterialTheme.typography.bodySmall)
                }
            }
            OutlinedButton(onClick = onTest,
                enabled = state.keySaved && !state.loading && !state.busy && !state.dirty,
                modifier = Modifier.fillMaxWidth()) {
                Text("Отправить тестовое уведомление")
            }
            Text("Тест отправляет одну служебную запись без личных данных. Доступ к уведомлениям телефона не нужен.", style = MaterialTheme.typography.bodySmall)
            Text("Ключ защищён Android Keystore. Для другого адреса Core введите ключ заново. AI-анализ и надёжная фоновая доставка ещё разрабатываются.", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun StatusRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(label, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
        Text(value, Modifier.weight(2f), style = MaterialTheme.typography.bodyMedium)
    }
}
