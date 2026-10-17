package com.shadeai.app.service

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import com.shadeai.app.ShadeApp
import com.shadeai.app.core.config.Allowlist
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.core.network.NotificationIngest
import com.shadeai.app.core.network.ShadeApi
import com.shadeai.app.data.db.PendingNotificationEntity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.CancellationException
import java.time.Instant

class ShadeNotificationListener : NotificationListenerService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onListenerConnected() {
        super.onListenerConnected()
        scope.launch { syncPending() }
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val pkg = sbn.packageName
        if (pkg !in Allowlist.packages) return

        val extras = sbn.notification.extras
        val title = extras?.getCharSequence(Notification.EXTRA_TITLE)?.toString() ?: return
        val text = extras?.getCharSequence(Notification.EXTRA_TEXT)?.toString() ?: return
        if (title.isBlank() && text.isBlank()) return

        scope.launch {
            val dao = ShadeApp.instance.database.pendingNotifications()
            val id = dao.insert(
                PendingNotificationEntity(
                    packageName = pkg,
                    title = title,
                    text = text,
                    postTime = sbn.postTime,
                )
            )
            sendOne(id, pkg, title, text, sbn.postTime)
        }
    }

    private suspend fun syncPending() {
        val dao = ShadeApp.instance.database.pendingNotifications()
        for (item in dao.unsent()) {
            sendOne(item.id, item.packageName, item.title, item.text, item.postTime)
        }
    }

    private suspend fun sendOne(id: Long, pkg: String, title: String, text: String, postTime: Long) {
        try {
            val settings = ServerPrefs.load(this)
            if (settings.apiKey.isEmpty()) return
            val api = ShadeApi.create(settings.baseUrl, settings.apiKey)
            api.ingest(
                NotificationIngest(
                    appName = pkg,
                    title = title,
                    text = text,
                    timestamp = Instant.ofEpochMilli(postTime).toString(),
                )
            )
            ShadeApp.instance.database.pendingNotifications().markSent(id)
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
        }
    }
}
