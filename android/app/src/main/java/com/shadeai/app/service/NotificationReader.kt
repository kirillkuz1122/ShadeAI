package com.shadeai.app.service

import android.app.Notification

class NotificationContent(val title: String, val text: String) {
    override fun toString() = "NotificationContent(redacted)"
}

object NotificationReader {
    fun read(notification: Notification, redactedText: String? = null): NotificationContent? = try {
        readFields(notification, redactedText)
    } catch (_: RuntimeException) { null }

    @Suppress("DEPRECATION")
    private fun readFields(notification: Notification, redactedText: String?): NotificationContent? {
        if (notification.flags and (Notification.FLAG_ONGOING_EVENT or Notification.FLAG_FOREGROUND_SERVICE or
                    Notification.FLAG_GROUP_SUMMARY or Notification.FLAG_LOCAL_ONLY) != 0) return null
        val extras = notification.extras
        if (extras?.containsKey(Notification.EXTRA_MESSAGES) == true) return null
        // Типизированные Bundle-getters логируют ошибочные значения; проверяем тип без таких логов.
        fun field(key: String): String {
            val value = extras?.get(key) ?: return ""
            require(value is CharSequence)
            return value.toString()
        }
        val title = field(Notification.EXTRA_TITLE)
        val expandedTitle = field(Notification.EXTRA_TITLE_BIG)
        val text = field(Notification.EXTRA_TEXT)
        val bigText = field(Notification.EXTRA_BIG_TEXT)
        val rawLines = extras?.get(Notification.EXTRA_TEXT_LINES)
        if (rawLines != null && (rawLines !is Array<*> || rawLines.size > 100)) return null
        val lines = (rawLines as? Array<*>)?.mapNotNull {
            if (it == null) null else { require(it is CharSequence); it.toString() }
        }.orEmpty()
        val ticker = notification.tickerText?.toString().orEmpty()
        val candidates = listOf(title, expandedTitle, text, bigText, ticker, field(Notification.EXTRA_SUB_TEXT)) + lines
        if (candidates.sumOf { it.length.toLong() } > 32768) return null
        // Проверяем и свёрнутый, и расширенный текст до выбора/нормализации, без усечения секретов.
        if (candidates.any { it.isNotBlank() && (it == redactedText || !NotificationPolicy.safeText(it)) }) return null
        val pickedTitle = expandedTitle.ifBlank { title }.trim()
        val pickedText = bigText.ifBlank { lines.filter { it.isNotBlank() }.joinToString("\n") }
            .ifBlank { text }.ifBlank { ticker }.replace("\r\n", "\n").trim()
        if (!NotificationPolicy.contentAllowed(pickedTitle, pickedText)) return null
        return NotificationContent(pickedTitle, pickedText)
    }
}
