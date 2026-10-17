package com.shadeai.app.core.config

import android.content.Context

object NotificationSources {
    val catalog = linkedMapOf(
        "ru.ozon.app.android" to "Ozon",
        "com.wildberries.ru" to "Wildberries",
        "ru.yandex.taxi" to "Яндекс Go",
    )
    private const val PREFS = "notification_sources"

    fun load(context: Context): Set<String> =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getStringSet("selected", emptySet()).orEmpty().intersect(catalog.keys)

    fun save(context: Context, selected: Set<String>) {
        require(catalog.keys.containsAll(selected))
        check(context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putStringSet("selected", selected.toSet()).commit())
    }
}
