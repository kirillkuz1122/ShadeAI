package com.shadeai.app.ui

import android.app.Application
import android.content.Context
import android.content.SharedPreferences
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.core.network.*
import com.shadeai.app.voice.Microphone
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody

class VoiceViewModel(app:Application):AndroidViewModel(app){
    private val prefs=app.getSharedPreferences("shade_prefs",Context.MODE_PRIVATE)
    private val controller=VoiceController(viewModelScope,{
        withContext(Dispatchers.IO){
            val revision=ServerPrefs.revision(app);val saved=ServerPrefs.load(app)
            check(revision==ServerPrefs.revision(app))
            ResultsCredentials(revision,saved.baseUrl,saved.apiKey)
        }
    },{ServerPrefs.revision(app)},{saved->
        val api=ShadeApi.create(saved.baseUrl,saved.apiKey,voice=true)
        object:VoiceClient{
            override suspend fun descriptor()=api.voice()
            override suspend fun prepare(id:String,wav:ByteArray)=api.prepareVoice(id,wav.toRequestBody("audio/wav".toMediaType()))
            override suspend fun state(id:String)=api.voiceState(id)
            override suspend fun confirm(id:String,body:VoiceConfirmation)=api.confirmVoice(id,body)
            override suspend fun cancel(id:String)=api.cancelVoice(id)
        }
    },Microphone(app))
    val state=controller.state
    private val listener=SharedPreferences.OnSharedPreferenceChangeListener{_,key->if(key=="delivery_revision")controller.settingsChanged()}
    fun revision()=ServerPrefs.revision(getApplication())
    fun start(){prefs.registerOnSharedPreferenceChangeListener(listener);controller.start()}
    fun close(){prefs.unregisterOnSharedPreferenceChangeListener(listener);controller.close()}
    fun refresh()=controller.refresh()
    fun record(revision:String)=controller.record(revision)
    fun denied()=controller.permissionDenied()
    fun stopRecording()=controller.stopRecording()
    fun cancelCapture()=controller.cancelCapture()
    fun confirm()=controller.confirm()
    fun cancel()=controller.cancel()
    fun checkStatus()=controller.checkStatus()
    fun select(row:CoreVoiceRequest)=controller.select(row)
    override fun onCleared(){close();super.onCleared()}
}
