package com.shadeai.app.core.config

import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

class AddressException(val hint: String) : IllegalArgumentException(hint)

object ServerAddress {
    fun normalize(input: String, cleartextAllowed: (String) -> Boolean = { true }): String {
        val value = input.trim()
        if (value.length > 2048 || value.any { it.isWhitespace() || it.code < 32 }) {
            throw AddressException("Адрес слишком длинный или содержит пробелы")
        }
        val url = value.toHttpUrlOrNull()
            ?: throw AddressException("Укажите http:// или https:// и адрес Core")
        if (url.username.isNotEmpty() || url.password.isNotEmpty() || url.query != null || url.fragment != null) {
            throw AddressException("В адресе не должно быть логина, пароля, query или fragment")
        }
        if (url.encodedPath !in setOf("/", "/api/v1", "/api/v1/")) {
            throw AddressException("Нужен адрес Core без пути или с /api/v1/")
        }
        if (url.scheme == "http" && !cleartextAllowed(url.host)) {
            throw AddressException("HTTP для этого адреса запрещён. Используйте доверенный HTTPS или разрешите точный адрес в сборке")
        }
        return url.newBuilder().encodedPath("/api/v1/").build().toString()
    }

    fun validKey(value: String): Boolean = value.length >= 32 && value.all { it.code in 33..126 }
}
