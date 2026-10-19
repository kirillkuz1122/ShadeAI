package com.shadeai.app.ui

import com.shadeai.app.core.network.*
import com.shadeai.app.voice.VoiceRecorder
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import retrofit2.HttpException
import java.time.Instant
import java.util.UUID

private val voiceStates=setOf("pending","dispatching","accepted","failed","unknown","cancelled","expired")
private val voiceBusy=setOf("loading","preparing","recording","recognizing","executing")
private fun light(value:String)=Regex("light\\.[a-z0-9_]{1,249}").matches(value)
private fun hash(value:String)=Regex("[a-f0-9]{64}").matches(value)
fun knownVoiceRequest(v:CoreVoiceRequest)=runCatching {
    val id=UUID.fromString(v.id)
    id.version()==4 && id.toString()==v.id && hash(v.policyScope) && light(v.entityId) && v.action in setOf("turn_on","turn_off") &&
        v.alias.length in 1..64 && v.state in voiceStates && (v.transcription?.length?:0)<=512 &&
        (v.newState==null || v.newState in setOf("on","off","unknown","unavailable")) &&
        !Instant.parse(v.expiresAt).isBefore(Instant.parse(v.createdAt)) && Instant.parse(v.updatedAt)!=null
}.getOrDefault(false)
fun knownVoice(v:CoreVoice)=v.version==1 && hash(v.policyScope) && v.requiresConfirmation && v.maxAudioSeconds==10 &&
    v.sttStatus in setOf("disabled","not_configured","configured","busy","closed") && v.targets.size<=20 &&
    v.targets.all{it.alias.length in 1..64 && light(it.entityId)} && v.targets.map{it.alias}.distinct().size==v.targets.size &&
    v.requests.size<=20 && v.requests.all(::knownVoiceRequest)
fun voiceStatus(value:String)=when(value){
    "pending"->"Ожидает подтверждения";"dispatching"->"Выполнение ещё не подтверждено";"accepted"->"Команда принята Home Assistant"
    "failed"->"Команда не отправлена или отклонена";"unknown"->"Результат неизвестен. Проверьте устройство"
    "cancelled"->"Запрос отменён";"expired"->"Время подтверждения истекло";else->"Формат не поддерживается"
}
data class VoiceState(val page:CoreVoice?=null,val request:CoreVoiceRequest?=null,val phase:String="loading",val error:String?=null,val message:String?=null){override fun toString()="VoiceState(redacted)"}
class VoiceController(private val scope:CoroutineScope,private val credentials:suspend()->ResultsCredentials,
    private val revision:()->String,private val client:(ResultsCredentials)->VoiceClient,private val recorder:VoiceRecorder){
    private val mutable=MutableStateFlow(VoiceState());val state=mutable.asStateFlow()
    private var active=false;private var generation=0;private var job:Job?=null;private var displayed:String?=null
    private fun valid(token:Int,saved:ResultsCredentials)=active && token==generation && saved.revision==revision()
    fun start(){active=true;refresh()}
    fun close(){active=false;generation++;recorder.stop();job?.cancel();displayed=null;mutable.value=VoiceState()}
    fun settingsChanged(){val was=active;close();if(was)start()}
    fun permissionDenied(){mutable.value=mutable.value.copy(error="Разрешите микрофон для записи команды.")}
    private fun access(error:Exception)=error is HttpException && error.code() in setOf(401,403)
    fun refresh(message:String?=null){
        if(!active || mutable.value.phase in setOf("recording","recognizing","executing"))return
        job?.cancel();val token=++generation;displayed=null;mutable.value=VoiceState(message=message)
        job=scope.launch{
            try{
                val saved=credentials();require(saved.apiKey.isNotBlank());if(!valid(token,saved))return@launch
                val page=client(saved).descriptor();check(knownVoice(page))
                if(valid(token,saved)){displayed=saved.revision;mutable.value=VoiceState(page=page,phase="idle",message=message)}
            }catch(error:CancellationException){throw error
            }catch(error:Exception){if(active && token==generation)mutable.value=VoiceState(phase="idle",error=if(access(error))"Ключ не принят. Проверьте подключение."else "Голосовой ввод Core недоступен или формат не поддерживается.")}
        }
    }
    fun record(permissionRevision:String){
        val page=mutable.value.page?:return
        val seen=displayed?:return
        if(!active || mutable.value.phase in voiceBusy || !page.enabled || !page.sttAvailable || permissionRevision!=revision() || permissionRevision!=seen)return
        job?.cancel();val token=++generation;mutable.value=mutable.value.copy(request=null,phase="preparing",error=null,message=null)
        job=scope.launch{
            var wav:ByteArray?=null
            try{
                val saved=credentials();if(!valid(token,saved))return@launch
                if(saved.revision!=seen){refreshAfter("Настройки Core изменились. Проверьте подключение.");return@launch}
                mutable.value=mutable.value.copy(phase="recording")
                wav=recorder.record()
                if(!valid(token,saved))return@launch
                mutable.value=mutable.value.copy(phase="recognizing")
                val id=UUID.randomUUID().toString()
                val prepared=client(saved).prepare(id,wav)
                check(knownVoiceRequest(prepared) && prepared.id==id)
                if(!valid(token,saved))return@launch
                if(prepared.policyScope!=page.policyScope){refreshAfter("Условия Core изменились. Обновите и запишите заново.");return@launch}
                mutable.value=mutable.value.copy(request=prepared,phase="ready")
            }catch(error:CancellationException){throw error
            }catch(error:Exception){if(active && token==generation){
                if(access(error)){displayed=null;mutable.value=VoiceState(phase="idle",error="Ключ не принят. Проверьте подключение.")}
                else mutable.value=mutable.value.copy(phase="idle",request=null,error="Не удалось распознать разрешённую команду. Проверьте связь, микрофон и настройки Core.")
            }}finally{wav?.fill(0)}
        }
    }
    private fun refreshAfter(message:String){mutable.value=VoiceState(phase="idle");refresh(message)}
    fun stopRecording(){if(mutable.value.phase=="recording")recorder.stop()}
    fun cancelCapture(){
        if(mutable.value.phase !in setOf("preparing","recording","recognizing"))return
        generation++;recorder.stop();job?.cancel();mutable.value=mutable.value.copy(phase="idle",request=null,error=null,message="Запись и ожидание остановлены. Команда не подтверждалась.")
    }
    fun select(row:CoreVoiceRequest){
        if(mutable.value.phase in voiceBusy || !knownVoiceRequest(row) || mutable.value.page?.requests?.none{it.id==row.id}!=false)return
        mutable.value=mutable.value.copy(request=row,phase="ready",error=null,message=null);checkStatus()
    }
    fun checkStatus()=mutation("state")
    fun confirm()=mutation("confirm")
    fun cancel()=mutation("cancel")
    private fun mutation(action:String){
        val selected=mutable.value.request?:return
        val page=mutable.value.page?:return;val seen=displayed?:return
        if(!active || mutable.value.phase in voiceBusy)return
        if(action=="confirm" && (mutable.value.phase!="ready" || selected.state!="pending" || !page.enabled ||
                selected.policyScope!=page.policyScope || page.targets.none{it.alias==selected.alias && it.entityId==selected.entityId} ||
                !Instant.now().isBefore(Instant.parse(selected.expiresAt))))return
        job?.cancel();val token=++generation;mutable.value=mutable.value.copy(phase="executing",error=null,message=null)
        job=scope.launch{
            try{
                val saved=credentials();if(!valid(token,saved))return@launch
                if(saved.revision!=seen){refreshAfter("Настройки Core изменились. Проверьте запрос заново.");return@launch}
                val api=client(saved)
                val result=when(action){"confirm"->api.confirm(selected.id,VoiceConfirmation(selected.policyScope,true));"cancel"->api.cancel(selected.id);else->api.state(selected.id)}
                check(knownVoiceRequest(result) && result.id==selected.id && result.policyScope==selected.policyScope)
                if(valid(token,saved))mutable.value=mutable.value.copy(request=result,phase="ready")
            }catch(error:CancellationException){throw error
            }catch(error:Exception){if(active && token==generation){
                if(access(error)){displayed=null;mutable.value=VoiceState(phase="idle",error="Ключ не принят. Проверьте подключение.")}
                else mutable.value=mutable.value.copy(phase="uncertain",error="Результат запроса не подтверждён. Проверьте состояние; автоматического повтора нет.")
            }}
        }
    }
}
