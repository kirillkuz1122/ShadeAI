package com.shadeai.app.service

import android.annotation.SuppressLint
import android.content.res.Resources
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import com.shadeai.app.ShadeApp
import com.shadeai.app.core.config.NotificationSources
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel

class ShadeNotificationListener : NotificationListenerService() {
    private sealed interface Callback {
        class Posted(val pkg: String, val content: NotificationContent, val postTime: Long, val key: String) : Callback
        class Removed(val key: String) : Callback
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var session: Job? = null
    private var callbacks: Channel<Callback>? = null
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
        stopSession()
        val incoming = Channel<Callback>(128)
        callbacks = incoming
        val activeKeys = try {
            activeNotifications?.filter { it.packageName in NotificationSources.catalog }
                ?.map { NotificationIdentity.hash(it.key) }?.toSet()
        } catch (_: RuntimeException) { null }
        session = scope.launch {
            val capture = ShadeApp.instance.capture
            capture.connected(activeKeys)
            ShadeApp.instance.delivery.wake()
            for (event in incoming) {
                when (event) {
                    is Callback.Posted -> {
                        val id = capture.record(event.pkg, event.content.title, event.content.text, event.postTime, event.key)
                        if (id != null) ShadeApp.instance.delivery.wake()
                    }
                    is Callback.Removed -> capture.removed(event.key)
                }
            }
        }
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val queue = callbacks ?: return
        if (sbn.packageName !in NotificationSources.catalog) return
        val content = NotificationReader.read(sbn.notification, redactedText) ?: return
        queue.trySend(Callback.Posted(sbn.packageName, content, sbn.postTime, NotificationIdentity.hash(sbn.key)))
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification) {
        if (sbn.packageName in NotificationSources.catalog) {
            callbacks?.trySend(Callback.Removed(NotificationIdentity.hash(sbn.key)))
        }
    }

    private fun stopSession() {
        callbacks?.close(); callbacks = null
        session?.cancel(); session = null
    }

    override fun onListenerDisconnected() {
        stopSession()
        scope.launch {
            try { ShadeApp.instance.capture.refresh() }
            catch (error: CancellationException) { throw error }
            catch (_: Exception) { }
        }
        super.onListenerDisconnected()
    }

    override fun onDestroy() {
        stopSession()
        scope.cancel()
        super.onDestroy()
    }
}
