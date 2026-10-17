package com.shadeai.app.service

import android.app.Notification
import android.annotation.SuppressLint
import android.content.res.Resources
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import com.shadeai.app.ShadeApp
import com.shadeai.app.core.config.NotificationSources
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.cancelChildren
import kotlinx.coroutines.launch

class ShadeNotificationListener : NotificationListenerService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var connected = false
    private val redactedText by lazy { systemRedactedText() }

    @SuppressLint("DiscouragedApi")
    private fun systemRedactedText(): String? {
        // Android не публикует признак редактирования; сравниваем с локализованной строкой ОС.
        val resources = Resources.getSystem()
        val id = resources.getIdentifier("redacted_notification_message", "string", "android")
        return if (id == 0) null else resources.getString(id)
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        connected = true
        scope.launch { ShadeApp.instance.capture.sync() }
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (!connected || sbn.packageName !in NotificationSources.catalog) return
        val notification = sbn.notification
        if (notification.flags and (Notification.FLAG_ONGOING_EVENT or
                Notification.FLAG_FOREGROUND_SERVICE or Notification.FLAG_GROUP_SUMMARY or
                Notification.FLAG_LOCAL_ONLY) != 0) return
        val extras = notification.extras
        val title = extras?.getCharSequence(Notification.EXTRA_TITLE)?.toString() ?: return
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString() ?: return
        if (text == redactedText) return
        scope.launch {
            ShadeApp.instance.capture.receive(sbn.packageName, title, text, sbn.postTime)
        }
    }

    override fun onListenerDisconnected() {
        connected = false
        scope.coroutineContext.cancelChildren()
        scope.launch {
            try { ShadeApp.instance.capture.refresh() } catch (_: Exception) { }
        }
        super.onListenerDisconnected()
    }

    override fun onDestroy() {
        connected = false
        scope.cancel()
        super.onDestroy()
    }
}
