package com.shadeai.app.core.config

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SavedConnection(val baseUrl: String, val apiKey: String) {
    override fun toString() = "SavedConnection(redacted)"
}

class SettingsStorageException : Exception("Не удалось прочитать или сохранить настройки подключения")

object ServerPrefs {

    private const val PREFS = "shade_prefs"
    private const val KEY_BASE_URL = "base_url"
    private const val KEY_CIPHER = "api_key_cipher_v1"
    private const val KEY_ALIAS = "shade.connection.v1"

    const val DEFAULT_BASE_URL = "http://192.168.1.100:8000/api/v1/"

    @Synchronized
    fun load(context: Context): SavedConnection = safely {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val url = prefs.getString(KEY_BASE_URL, DEFAULT_BASE_URL) ?: DEFAULT_BASE_URL
        val encoded = prefs.getString(KEY_CIPHER, null)
        val key = if (encoded == null) "" else {
            val parts = encoded.split(":")
            require(parts.size == 2)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, secretKey(false), GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)))
            cipher.updateAAD(url.toByteArray(Charsets.UTF_8))
            String(cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)), Charsets.UTF_8)
        }
        SavedConnection(url, key)
    }

    @Synchronized
    fun save(context: Context, url: String, key: String) = safely {
        require(ServerAddress.validKey(key))
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, secretKey(true))
        // Привязка шифротекста к адресу защищает от переноса ключа на другой сервер.
        cipher.updateAAD(url.toByteArray(Charsets.UTF_8))
        val encoded = Base64.encodeToString(cipher.iv, Base64.NO_WRAP) + ":" +
            Base64.encodeToString(cipher.doFinal(key.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP)
        check(context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY_BASE_URL, url).putString(KEY_CIPHER, encoded).commit())
    }

    @Synchronized
    fun clearKey(context: Context) = safely {
        check(context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(KEY_CIPHER).commit())
    }

    private fun secretKey(create: Boolean): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        check(create)
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }

    private inline fun <T> safely(action: () -> T): T = try {
        action()
    } catch (_: Exception) {
        throw SettingsStorageException()
    }
}

object Allowlist {
    val packages = setOf(
        "ru.ozon.app.android",
        "com.wildberries.ru",
        "ru.yandex.taxi",
    )
}
