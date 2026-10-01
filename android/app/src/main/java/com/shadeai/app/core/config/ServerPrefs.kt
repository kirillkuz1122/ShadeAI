package com.shadeai.app.core.config

import android.content.Context

object ServerPrefs {

    private const val PREFS = "shade_prefs"
    private const val KEY_BASE_URL = "base_url"

    const val DEFAULT_BASE_URL = "http://192.168.1.100:8000/api/v1/"

    fun baseUrl(context: Context): String =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_BASE_URL, DEFAULT_BASE_URL) ?: DEFAULT_BASE_URL

    fun setBaseUrl(context: Context, url: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_BASE_URL, url.takeIf { it.endsWith("/") } ?: "$url/")
            .apply()
    }
}

object Allowlist {
    val packages = setOf(
        "org.telegram.messenger",
        "com.whatsapp",
        "ru.ozon.app.android",
        "com.wildberries.ru",
        "ru.yandex.taxi",
        "com.sberbank.mobile",
        "ru.sberbankmobile",
    )
}
