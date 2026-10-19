package com.shadeai.app.ui

import android.app.Application
import android.content.Context
import android.content.SharedPreferences
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.core.network.*
import com.shadeai.app.core.network.CalendarClient
import com.shadeai.app.core.network.ShadeApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class CalendarViewModel(application: Application) : AndroidViewModel(application) {
    private val prefs = application.getSharedPreferences("shade_prefs", Context.MODE_PRIVATE)
    private val loadCredentials: suspend () -> ResultsCredentials = {
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
    }
    private val controller = CalendarController(viewModelScope, credentials = loadCredentials, revision = { ServerPrefs.revision(application) }, client = { connection ->
        val api = ShadeApi.create(connection.baseUrl, connection.apiKey)
        object : CalendarClient {
            override suspend fun page(offset:Int,inactive:Boolean)=api.calendar(offset,inactive)
            override suspend fun sync()=api.syncCalendar()
        }
    })
    val meetings = MeetingController(viewModelScope,loadCredentials,{ServerPrefs.revision(application)}){connection->
        val api=ShadeApi.create(connection.baseUrl,connection.apiKey)
        object:MeetingClient {
            override suspend fun page()=api.meetingState()
            override suspend fun view(id:String)=api.meeting(id)
            override suspend fun decide(id:String,body:MeetingDecision)=api.decideMeeting(id,body)
            override suspend fun ack(entity:String,body:MeetingAck)=api.acknowledgeMeeting(entity,body)
        }
    }
    val state = controller.state
    private val listener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if (key == "delivery_revision") {controller.settingsChanged();meetings.settingsChanged()}
    }
    fun start() { prefs.registerOnSharedPreferenceChangeListener(listener); controller.start();meetings.start() }
    fun close() { prefs.unregisterOnSharedPreferenceChangeListener(listener); controller.close();meetings.close() }
    fun filter(value:Boolean)=controller.filter(value)
    fun sync()=controller.sync()
    fun next() = controller.next()
    fun previous() = controller.previous()
    fun refresh() = controller.refresh()
    override fun onCleared() { close(); super.onCleared() }
}
