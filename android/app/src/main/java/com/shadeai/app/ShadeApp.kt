package com.shadeai.app

import android.app.Application
import com.shadeai.app.data.db.AppDatabase

class ShadeApp : Application() {

    val database: AppDatabase by lazy {
        AppDatabase.create(this)
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
