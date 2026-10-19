package com.shadeai.app

import android.app.Application
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkRequest
import com.shadeai.app.core.config.NotificationSources
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.core.config.SettingsStorageException
import com.shadeai.app.core.network.DeliveryFailure
import com.shadeai.app.core.network.ShadeApi
import com.shadeai.app.core.network.sendNotification
import com.shadeai.app.data.db.AppDatabase
import com.shadeai.app.data.db.DeliveryStatus
import com.shadeai.app.service.NotificationAccess
import com.shadeai.app.service.NotificationCapture
import com.shadeai.app.service.NotificationDeliveryScheduler

class ShadeApp : Application() {

    val database: AppDatabase by lazy {
        AppDatabase.create(this)
    }

    val delivery by lazy { NotificationDeliveryScheduler(this) }

    val capture: NotificationCapture by lazy {
        NotificationCapture(database.pendingNotifications(),
            selected = { NotificationSources.load(this) },
            save = { NotificationSources.save(this, it) },
            access = { NotificationAccess.granted(this) },
            send = { item ->
                val settings = try { ServerPrefs.load(this) }
                    catch (_: SettingsStorageException) { throw DeliveryFailure("configuration", pause = true) }
                if (settings.apiKey.isEmpty()) DeliveryStatus.PENDING else {
                    sendNotification(ShadeApi.create(settings.baseUrl, settings.apiKey), item)
                }
            }, revision = { ServerPrefs.revision(this) })
    }

    companion object {
        lateinit var instance: ShadeApp
            private set
    }

    private val reminderSettings = android.content.SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if(key=="delivery_revision")com.shadeai.app.reminders.ReminderDelivery.checkNow(this)
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
        delivery.start()
        getSharedPreferences("shade_prefs",MODE_PRIVATE).registerOnSharedPreferenceChangeListener(reminderSettings)
        com.shadeai.app.reminders.ReminderDelivery.start(this)
        if(com.shadeai.app.reminders.ReminderPrefs.items(this).isNotEmpty())
            com.shadeai.app.reminders.ReminderDelivery.checkNow(this)
        getSystemService(ConnectivityManager::class.java).registerNetworkCallback(
            NetworkRequest.Builder().build(), object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) { delivery.networkAvailable() }
            })
    }
}
