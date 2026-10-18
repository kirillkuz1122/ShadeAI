package com.shadeai.app.ui

import android.app.Application
import android.content.Context
import android.content.SharedPreferences
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.core.network.ResultsClient
import com.shadeai.app.core.network.ShadeApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class CoreResultsViewModel(application: Application) : AndroidViewModel(application) {
    private val prefs = application.getSharedPreferences("shade_prefs", Context.MODE_PRIVATE)
    private val controller = CoreResultsController(viewModelScope, credentials = {
        withContext(Dispatchers.IO) {
            var saved: ResultsCredentials? = null
            repeat(3) {
                if (saved == null) {
                    val before = ServerPrefs.revision(application)
                    val connection = ServerPrefs.load(application)
                    if (before == ServerPrefs.revision(application))
                        saved = ResultsCredentials(before, connection.baseUrl, connection.apiKey)
                }
            }
            checkNotNull(saved)
        }
    }, currentRevision = { ServerPrefs.revision(application) }, createClient = { connection ->
        val api = ShadeApi.create(connection.baseUrl, connection.apiKey)
        object : ResultsClient {
            override suspend fun list(limit: Int, offset: Int) = api.notifications(limit, offset)
            override suspend fun detail(id: Long) = api.notification(id)
        }
    })
    val state = controller.state
    private val listener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if (key == "delivery_revision") controller.settingsChanged()
    }
    fun start() { prefs.registerOnSharedPreferenceChangeListener(listener); controller.start() }
    fun close() { prefs.unregisterOnSharedPreferenceChangeListener(listener); controller.close() }
    fun select(id: Long?) = controller.select(id)
    fun next() = controller.next()
    fun previous() = controller.previous()
    fun refresh() = controller.refresh()
    override fun onCleared() { close(); super.onCleared() }
}
