package com.shadeai.app

import android.app.Application
import com.shadeai.app.data.db.AppDatabase
import com.shadeai.app.core.config.NotificationSources
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.core.network.NotificationIngest
import com.shadeai.app.core.network.ShadeApi
import com.shadeai.app.service.NotificationAccess
import com.shadeai.app.service.NotificationCapture
import java.time.Instant

class ShadeApp : Application() {

    val database: AppDatabase by lazy {
        AppDatabase.create(this)
    }

    val capture: NotificationCapture by lazy {
        NotificationCapture(database.pendingNotifications(),
            selected = { NotificationSources.load(this) },
            save = { NotificationSources.save(this, it) },
            access = { NotificationAccess.granted(this) },
            send = { item ->
                val settings = ServerPrefs.load(this)
                if (settings.apiKey.isEmpty()) false else {
                    ShadeApi.create(settings.baseUrl, settings.apiKey).ingest(NotificationIngest(
                        appName = item.packageName, title = item.title, text = item.text,
                        timestamp = Instant.ofEpochMilli(item.postTime).toString(),
                    ))
                    true
                }
            })
    }

    companion object {
        lateinit var instance: ShadeApp
            private set
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
    }
}
