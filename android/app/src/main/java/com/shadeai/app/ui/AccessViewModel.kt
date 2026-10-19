package com.shadeai.app.ui

import android.app.Application
import android.content.Context
import android.content.SharedPreferences
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.core.network.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class AccessViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs=app.getSharedPreferences("shade_prefs",Context.MODE_PRIVATE)
    private val controller=AccessController(viewModelScope,{
        withContext(Dispatchers.IO) {
            val revision=ServerPrefs.revision(app); val saved=ServerPrefs.load(app)
            check(revision==ServerPrefs.revision(app))
            ResultsCredentials(revision,saved.baseUrl,saved.apiKey)
        }
    },{ServerPrefs.revision(app)},{saved ->
        val api=ShadeApi.create(saved.baseUrl,saved.apiKey)
        object: AccessClient {
            override suspend fun descriptor()=api.access()
            override suspend fun create(body: AccessCreation)=api.createAccess(body)
            override suspend fun state(id: String)=api.accessState(id)
            override suspend fun revoke(id: String,body: AccessRevocation)=api.revokeAccess(id,body)
        }
    },{saved ->
        val api=ShadeApi.create(saved.baseUrl,saved.apiKey)
        object: ResultsClient {
            override suspend fun list(limit: Int,offset: Int)=api.notifications(limit,offset)
            override suspend fun detail(id: Long)=api.notification(id)
        }
    })
    val state=controller.state
    private val listener=SharedPreferences.OnSharedPreferenceChangeListener { _,key ->
        if(key=="delivery_revision") controller.settingsChanged()
    }
    fun start(secure: Boolean) { prefs.registerOnSharedPreferenceChangeListener(listener); controller.start(secure) }
    fun close() { prefs.unregisterOnSharedPreferenceChangeListener(listener); controller.close() }
    fun refresh(offset: Int=state.value.offset)=controller.refresh(offset)
    fun selectSource(id: Long)=controller.selectSource(id)
    fun target(value: String)=controller.target(value)
    fun minutes(value: Int)=controller.minutes(value)
    fun deliveryChecked(value: Boolean)=controller.deliveryChecked(value)
    fun unlockChecked(value: Boolean)=controller.unlockChecked(value)
    fun manualChecked(value: Boolean)=controller.manualChecked(value)
    fun create()=controller.create()
    fun selectGrant(id: String)=controller.selectGrant(id)
    fun checkStatus()=controller.checkStatus()
    fun revoke()=controller.revoke()
    fun hidePin()=controller.hidePin()
    override fun onCleared() { close(); super.onCleared() }
}
