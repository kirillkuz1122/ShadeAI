package com.shadeai.app.service

import android.app.NotificationManager
import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.provider.Settings

object NotificationAccess {
    fun granted(context: Context): Boolean {
        val component = ComponentName(context, ShadeNotificationListener::class.java)
        return if (Build.VERSION.SDK_INT >= 27) {
            context.getSystemService(NotificationManager::class.java).isNotificationListenerAccessGranted(component)
        } else {
            Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners")
                .orEmpty().split(':').any { ComponentName.unflattenFromString(it) == component }
        }
    }
}
