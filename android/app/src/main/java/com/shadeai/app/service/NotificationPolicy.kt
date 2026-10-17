package com.shadeai.app.service

import com.shadeai.app.core.config.NotificationSources

object NotificationPolicy {
    private val words = Regex("[\\p{L}\\p{N}_]+")
    private val exact = setOf("code", "otp", "pin", "password", "cvv", "cvc")

    private fun sensitive(value: String) = words.findAll(value).any {
        val word = it.value.lowercase()
        word in exact || word.startsWith("код") || word.startsWith("парол") || word.startsWith("пин")
    }

    fun safeText(text: String): Boolean =
        text.length <= 8192 && text.trim() != "Sensitive notification content hidden" && !sensitive(text)

    fun contentAllowed(title: String, text: String): Boolean =
        (title.isNotBlank() || text.isNotBlank()) && title.length <= 512 && safeText(title) && safeText(text)

    fun allows(pkg: String, title: String, text: String, selected: Set<String>): Boolean =
        pkg in NotificationSources.catalog && pkg in selected && contentAllowed(title, text)
}
