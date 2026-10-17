package com.shadeai.fixture

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Bundle

class PublisherActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("task10", "Синтетическая проверка", NotificationManager.IMPORTANCE_DEFAULT))
        val kind = intent.getStringExtra("kind") ?: "order"
        val id = intent.getIntExtra("id", 1)
        if (kind == "cancel") { manager.cancel(id); finish(); return }
        val variant = intent.getStringExtra("variant") ?: "original"
        val notification = Notification.Builder(this, "task10")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("Синтетическая доставка $kind")
            .setContentText(if (kind in setOf("sensitive", "hidden-sensitive")) "Код 1234 — синтетическая проверка"
                else "Заказ подготовлен — синтетическая проверка")
            .setOngoing(kind == "ongoing")
            .setLocalOnly(kind == "local")
        when (kind) {
            "big", "hidden-sensitive" -> notification.setStyle(Notification.BigTextStyle()
                .bigText(if (variant == "updated") "Курьер подъезжает. Доставка скоро прибудет"
                    else "Курьер в пути. Доставка ожидается вечером"))
            "inbox" -> notification.setStyle(Notification.InboxStyle().addLine("Заказ принят").addLine("Передан курьеру"))
            "ticker" -> notification.setTicker("Синтетическая доставка готова")
            "summary" -> notification.setGroup("task10").setGroupSummary(true)
        }
        val built = notification.build()
        if (kind == "ticker") { built.extras.remove(Notification.EXTRA_TITLE); built.extras.remove(Notification.EXTRA_TEXT) }
        if (kind == "title-only") built.extras.remove(Notification.EXTRA_TEXT)
        if (kind == "foreground") built.flags = built.flags or Notification.FLAG_FOREGROUND_SERVICE
        manager.notify(id, built)
        finish()
    }
}
