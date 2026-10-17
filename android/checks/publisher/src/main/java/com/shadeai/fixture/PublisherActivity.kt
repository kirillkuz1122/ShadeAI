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
        val notification = Notification.Builder(this, "task10")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("Синтетическая доставка $kind")
            .setContentText(if (kind == "sensitive") "Код 1234 — синтетическая проверка" else "Заказ подготовлен — синтетическая проверка")
            .setOngoing(kind == "ongoing")
            .setLocalOnly(kind == "local")
        if (kind == "summary") notification.setGroup("task10").setGroupSummary(true)
        if (kind == "foreground") {
            val built = notification.build()
            built.flags = built.flags or Notification.FLAG_FOREGROUND_SERVICE
            manager.notify(id, built)
        } else manager.notify(id, notification.build())
        finish()
    }
}
