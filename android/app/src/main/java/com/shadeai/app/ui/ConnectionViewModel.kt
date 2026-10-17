package com.shadeai.app.ui

import android.app.Application
import android.security.NetworkSecurityPolicy
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.shadeai.app.core.config.AddressException
import com.shadeai.app.core.config.ServerAddress
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.core.config.SettingsStorageException
import com.shadeai.app.core.network.HealthResponse
import com.shadeai.app.core.network.MissingCredentialsException
import com.shadeai.app.core.network.NotificationIngest
import com.shadeai.app.core.network.ShadeApi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.supervisorScope
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerializationException
import retrofit2.HttpException
import java.io.IOException
import java.io.InterruptedIOException
import java.time.Instant
import java.util.UUID
import javax.net.ssl.SSLException

data class ConnectionUiState(
    val url: String = ServerPrefs.DEFAULT_BASE_URL,
    val keyInput: String = "",
    val keySaved: Boolean = false,
    val loading: Boolean = true,
    val busy: Boolean = false,
    val dirty: Boolean = false,
    val addressError: String? = null,
    val keyError: String? = null,
    val health: HealthResponse? = null,
    val coreMessage: String = "Не проверено",
    val accessMessage: String = "Не проверено",
    val message: String = "",
) {
    override fun toString() = "ConnectionUiState(redacted)"
}

private class NetworkResult<T>(val value: T? = null, val error: String? = null)

class ConnectionViewModel(application: Application) : AndroidViewModel(application) {
    private val mutable = MutableStateFlow(ConnectionUiState())
    val state = mutable.asStateFlow()
    private var request: Job? = null
    private var generation = 0

    init {
        request = viewModelScope.launch {
            try {
                val saved = withContext(Dispatchers.IO) { ServerPrefs.load(getApplication()) }
                mutable.update { it.copy(url = saved.baseUrl, keySaved = saved.apiKey.isNotEmpty(), loading = false) }
            } catch (_: SettingsStorageException) {
                mutable.update { it.copy(loading = false, message = "Не удалось прочитать ключ. Удалите его и сохраните заново.") }
            }
        }
    }

    fun editUrl(value: String) {
        invalidate()
        mutable.update { it.copy(url = value, dirty = true, busy = false, health = null,
            addressError = null, coreMessage = "Не проверено", accessMessage = "Не проверено", message = "Изменения не сохранены") }
    }

    fun editKey(value: String) {
        invalidate()
        mutable.update { it.copy(keyInput = value, dirty = true, busy = false, keyError = null,
            accessMessage = "Не проверено", message = "Изменения не сохранены") }
    }

    private fun invalidate(): Int {
        request?.cancel()
        return ++generation
    }

    fun saveAndCheck() {
        val input = mutable.value
        val current = invalidate()
        val url = try {
            ServerAddress.normalize(input.url) { NetworkSecurityPolicy.getInstance().isCleartextTrafficPermitted(it) }
        } catch (error: AddressException) {
            mutable.update { it.copy(addressError = error.hint, busy = false) }
            return
        }
        val entered = input.keyInput.trim()
        if (entered.isNotEmpty() && !ServerAddress.validKey(entered)) {
            mutable.update { it.copy(keyError = "Нужно не менее 32 ASCII-символов без пробелов", busy = false) }
            return
        }
        mutable.update { it.copy(busy = true, addressError = null, keyError = null, message = "Сохранение…") }
        request = viewModelScope.launch {
            try {
                val saved = withContext(Dispatchers.IO) { ServerPrefs.load(getApplication()) }
                val key = entered.ifEmpty { if (saved.baseUrl == url) saved.apiKey else "" }
                if (key.isEmpty()) {
                    mutable.update { it.copy(busy = false, keyError = "Введите ключ для этого адреса Core", message = "Настройки не изменены") }
                    return@launch
                }
                withContext(Dispatchers.IO) { ServerPrefs.save(getApplication(), url, key) }
                if (generation != current) return@launch
                mutable.update { it.copy(url = url, keyInput = "", keySaved = true, dirty = false,
                    health = null, coreMessage = "Проверка…", accessMessage = "Проверка…", message = "Настройки сохранены") }
                val api = ShadeApi.create(url, key)
                supervisorScope {
                    val health = async { attempt { api.health() } }
                    val access = async { attempt { api.verifyAccess() } }
                    val h = health.await()
                    val a = access.await()
                    if (generation == current) mutable.update { it.copy(busy = false, health = h.value,
                        coreMessage = h.error ?: if (h.value?.status == "ok") "Core доступен" else "Core доступен частично",
                        accessMessage = a.error ?: "Ключ принят", message = "Проверка завершена") }
                }
            } catch (error: CancellationException) {
                throw error
            } catch (_: SettingsStorageException) {
                if (generation == current) mutable.update { it.copy(busy = false, message = "Не удалось сохранить настройки. Ключ можно удалить и ввести заново.") }
            }
        }
    }

    fun clearKey() {
        val current = invalidate()
        mutable.update { it.copy(busy = true, keyInput = "", health = null, accessMessage = "Не проверено") }
        request = viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { ServerPrefs.clearKey(getApplication()) }
                if (generation == current) mutable.update { it.copy(busy = false, keySaved = false, keyError = null,
                    coreMessage = "Не проверено", message = "Ключ удалён с устройства") }
            } catch (_: SettingsStorageException) {
                if (generation == current) mutable.update { it.copy(busy = false, message = "Не удалось удалить ключ. Повторите попытку.") }
            }
        }
    }

    fun sendTest() {
        val current = invalidate()
        mutable.update { it.copy(busy = true, message = "Отправка служебной записи…") }
        request = viewModelScope.launch {
            try {
                val settings = withContext(Dispatchers.IO) { ServerPrefs.load(getApplication()) }
                val result = attempt {
                    ShadeApi.create(settings.baseUrl, settings.apiKey).ingest(NotificationIngest(
                        appName = "ru.ozon.app.android", title = "Проверка подключения Shade",
                        text = "Служебное уведомление без личных данных", timestamp = Instant.now().toString(),
                        eventId = UUID.randomUUID().toString(),
                    ))
                }
                if (generation == current) mutable.update { it.copy(busy = false, message = result.error ?: when (result.value?.status) {
                    "stored", "duplicate" -> "Тест сохранён в Core: #${result.value.id}"
                    "skipped" -> "Ключ принят, но Core пропустил тест по правилам хранения"
                    else -> "Core вернул неожиданный ответ"
                }) }
            } catch (error: CancellationException) {
                throw error
            } catch (_: SettingsStorageException) {
                if (generation == current) mutable.update { it.copy(busy = false, message = "Не удалось прочитать сохранённый ключ") }
            }
        }
    }

    private suspend fun <T> attempt(action: suspend () -> T): NetworkResult<T> = try {
        NetworkResult(value = action())
    } catch (error: CancellationException) {
        throw error
    } catch (_: MissingCredentialsException) {
        NetworkResult(error = "Ключ Core не задан")
    } catch (error: HttpException) {
        NetworkResult(error = when (error.code()) {
            401, 403 -> "Ключ не принят"
            in 300..399 -> "Core вернул перенаправление. Укажите конечный адрес"
            404 -> "API Core не найден по этому адресу"
            in 500..599 -> "Core ответил ошибкой сервера"
            else -> "Core отклонил запрос (HTTP ${error.code()})"
        })
    } catch (_: SSLException) {
        NetworkResult(error = "Не удалось проверить TLS-сертификат Core")
    } catch (_: InterruptedIOException) {
        NetworkResult(error = "Время ожидания Core истекло")
    } catch (_: IOException) {
        NetworkResult(error = "Нет соединения с Core. Проверьте локальную сеть")
    } catch (_: SerializationException) {
        NetworkResult(error = "Ответ сервера не соответствует API Core")
    } catch (_: IllegalArgumentException) {
        NetworkResult(error = "Некорректные настройки подключения")
    }
}
