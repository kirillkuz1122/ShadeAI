package com.shadeai.app.ui

import android.app.Application
import android.content.Context
import android.content.SharedPreferences
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.core.network.*
import com.shadeai.app.hints.HintDelivery
import com.shadeai.app.hints.HintPrefs
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

data class HintSettingsState(val enabled:Boolean=false,val busy:Boolean=false,val error:String?=null)
class SuggestionsViewModel(application:Application):AndroidViewModel(application) {
    private val app=application
    private val prefs=app.getSharedPreferences("shade_prefs",Context.MODE_PRIVATE)
    private val controller=SuggestionsController(viewModelScope,credentials={withContext(Dispatchers.IO){
        var value:ResultsCredentials?=null
        repeat(3){if(value==null){val revision=ServerPrefs.revision(app);val saved=ServerPrefs.load(app)
            if(revision==ServerPrefs.revision(app))value=ResultsCredentials(revision,saved.baseUrl,saved.apiKey)}}
        checkNotNull(value)
    }},revision={ServerPrefs.revision(app)},client={saved->
        val api=ShadeApi.create(saved.baseUrl,saved.apiKey)
        object:SuggestionsClient {
            override suspend fun list(offset:Int)=api.automations(offset)
            override suspend fun hints(afterId:Long)=api.hints(afterId)
            override suspend fun detail(id:String)=api.automation(id)
            override suspend fun decide(id:String,decision:RuleDecision)=api.decideAutomation(id,decision)
            override suspend fun refresh()=api.refreshAutomations()
        }
    })
    val state=controller.state
    private val mutableHints=MutableStateFlow(HintSettingsState())
    val hintSettings=mutableHints.asStateFlow()
    private val listener=SharedPreferences.OnSharedPreferenceChangeListener {_,key->if(key=="delivery_revision"){
        controller.settingsChanged();readHintSettings()
    }}
    fun start(){prefs.registerOnSharedPreferenceChangeListener(listener);controller.start();readHintSettings()}
    fun close(){prefs.unregisterOnSharedPreferenceChangeListener(listener);controller.close()}
    fun refresh()=controller.refresh()
    fun update()=controller.updateSuggestions()
    fun history(id:String?)=controller.history(id)
    fun nextHints()=controller.nextHints()
    fun next()=controller.next()
    fun previous()=controller.previous()
    fun decide(row:CoreRule,decision:String,target:String?=null)=controller.decide(row,decision,target)
    fun revision()=ServerPrefs.revision(app)
    private fun readHintSettings(){mutableHints.value=HintSettingsState(HintPrefs.enabled(app),error=when(HintPrefs.error(app)){
        "access"->"Ключ Core не принят. Проверьте подключение и повторите проверку."
        "unsupported"->"Core пока не поддерживает подсказки. Обновите сервер."
        else->null
    })}
    fun permissionDenied(){mutableHints.value=HintSettingsState(HintPrefs.enabled(app),error="Android не разрешил системные уведомления.")}
    fun setHints(enabled:Boolean,revision:String=revision()) {
        if(mutableHints.value.busy)return
        mutableHints.value=mutableHints.value.copy(busy=true,error=null)
        viewModelScope.launch {
            try {withContext(Dispatchers.IO){HintDelivery.setEnabled(app,enabled,revision)};readHintSettings()
            }catch(error:CancellationException){throw error
            }catch(_:Exception){mutableHints.value=HintSettingsState(HintPrefs.enabled(app),error="Проверьте ключ Core и разрешение уведомлений Android.")}
        }
    }
    fun checkHints(){HintDelivery.checkNow(app,resume=true);readHintSettings()}
    override fun onCleared(){close();super.onCleared()}
}
