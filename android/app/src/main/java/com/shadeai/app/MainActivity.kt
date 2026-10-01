package com.shadeai.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.core.network.ShadeApi
import com.shadeai.app.ui.theme.ShadeAITheme
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            ShadeAITheme {
                StatusScreen()
            }
        }
    }

    @Composable
    private fun StatusScreen() {
        var baseUrl by remember { mutableStateOf(ServerPrefs.baseUrl(this)) }
        var status by remember { mutableStateOf("Не проверено") }
        val scope = rememberCoroutineScope()

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.height(32.dp))
            Text("Shade AI", style = MaterialTheme.typography.displaySmall)
            Text("Клиент умного дома", style = MaterialTheme.typography.bodyMedium)

            OutlinedTextField(
                value = baseUrl,
                onValueChange = { baseUrl = it },
                label = { Text("Адрес Shade Core") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )

            Button(
                onClick = {
                    ServerPrefs.setBaseUrl(this@MainActivity, baseUrl.trim())
                    scope.launch {
                        status = try {
                            val api = ShadeApi.create(ServerPrefs.baseUrl(this@MainActivity))
                            val health = api.health()
                            "Статус: ${health.status}, HA: ${if (health.haConnected) "подключен" else "нет"}, LLM: ${health.llmStatus}"
                        } catch (e: Exception) {
                            "Нет связи: ${e.message ?: "ошибка сети"}"
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Проверить связь")
            }

            Text(status, style = MaterialTheme.typography.bodyLarge)
        }
    }
}
