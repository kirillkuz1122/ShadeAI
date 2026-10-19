package com.shadeai.app.ui

import com.shadeai.app.core.network.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.time.Instant
import java.util.UUID
import retrofit2.HttpException

private fun entity(value:String)=Regex("switch\\.[a-z0-9_]{1,248}").matches(value)
private fun event(value:String)=Regex("cal_[a-f0-9]{32}").matches(value)
private fun targets(values:List<String>)=values.size<=5 && values.distinct().size==values.size && values.all(::entity)
fun knownMeetingPolicy(p:MeetingPolicy)=p.version==1 && p.maxDurationSeconds==28800 && targets(p.allowedTargets)
fun knownMeeting(v:CoreMeeting)=runCatching {
    Instant.parse(v.startsAt);Instant.parse(v.endsAt)
    knownMeetingPolicy(v.policy) && event(v.eventId) && v.eventRevision>0 && Regex("[a-f0-9]{64}").matches(v.policyScope) &&
        v.status in listOf("not_approved","approved","disabled","needs_review","finished") && targets(v.targets) && targets(v.startedTargets)
}.getOrDefault(false)
fun knownMeetingPage(p:CoreMeetingPage)=runCatching {
    knownMeetingPolicy(p.policy) && p.leases.size<=100 && p.history.size<=50 && p.leases.all {
        Instant.parse(it.updatedAt)
        entity(it.entityId) && UUID.fromString(it.generation).toString()==it.generation && it.state in meetingStates &&
            it.members.size<=200 && it.members.all(::event)
    } && p.history.all{it.id>0 && entity(it.entityId) && it.state in meetingStates}
}.getOrDefault(false)
val meetingStates=mapOf("waiting" to "Ожидание устройства","applying" to "Команда включения отправляется","active" to "Включение наблюдалось",
    "external" to "Уже было включено — не выключаем","restoring" to "Восстановление отправляется","completed" to "Обработка завершена",
    "unknown" to "Результат неизвестен — проверьте устройство")
fun meetingStatus(value:String)=meetingStates[value]?:when(value){"approved"->"Согласие сохранено";"disabled"->"Выключен";"needs_review"->"Нужно новое подтверждение";"finished"->"Встреча завершена";else->"Не подтверждён"}
fun meetingReason(value:String?)=when(value){"RESTORE_OBSERVED"->"Выключение наблюдалось";"MANUAL_CHANGE_PRESERVED"->"Ручное изменение сохранено";"CORE_RESTARTED"->"Core перезапустился во время команды";"POLICY_REVOKED"->"Разрешение на устройство отозвано";else->null}
data class MeetingState(val selected:String?=null,val page:CoreMeetingPage?=null,val view:CoreMeeting?=null,val loading:Boolean=true,val busy:Boolean=false,val error:String?=null,val message:String?=null){override fun toString()="MeetingState(redacted)"}
class MeetingController(private val scope:CoroutineScope,private val credentials:suspend()->ResultsCredentials,
    private val revision:()->String,private val client:(ResultsCredentials)->MeetingClient){
    private val mutable=MutableStateFlow(MeetingState());val state=mutable.asStateFlow()
    private var active=false;private var generation=0;private var job:Job?=null;private var displayed:String?=null
    fun start(){active=true;refresh()}
    fun close(){active=false;generation++;job?.cancel();displayed=null;mutable.value=MeetingState()}
    fun settingsChanged(){val was=active;close();if(was)start()}
    fun select(id:String?){if(id!=null && !event(id))return;mutable.value=MeetingState(selected=id);refresh()}
    private fun valid(token:Int,saved:ResultsCredentials)=active && generation==token && saved.revision==revision()
    fun refresh(message:String?=null){
        if(!active)return
        job?.cancel();val token=++generation;displayed=null
        val id=mutable.value.selected;mutable.value=MeetingState(selected=id,message=message)
        job=scope.launch{
            try{
                val saved=credentials();require(saved.apiKey.isNotBlank());if(!valid(token,saved))return@launch
                val api=client(saved);val page=api.page();check(knownMeetingPage(page))
                val view=id?.let{api.view(it).also{v->check(knownMeeting(v) && v.eventId==id)}}
                if(valid(token,saved)){displayed=saved.revision;mutable.value=MeetingState(id,page,view,loading=false,message=message)}
            }catch(error:CancellationException){throw error
            }catch(error:Exception){if(active && generation==token)mutable.value=MeetingState(id,loading=false,error=
                if(error is HttpException && error.code() in listOf(401,403))"Ключ не принят. Проверьте подключение."else "Режим встречи недоступен или формат не поддерживается.")}
        }
    }
    private fun mutate(action:suspend(MeetingClient)->Unit){
        val seen=displayed?:return;if(!active || mutable.value.busy || mutable.value.loading)return
        job?.cancel();val token=++generation;mutable.value=mutable.value.copy(busy=true,message=null)
        job=scope.launch{
            try{
                val saved=credentials()
                if(!valid(token,saved))return@launch
                if(saved.revision!=seen){refresh("Настройки Core изменились. Проверьте условия заново.");return@launch}
                action(client(saved));if(valid(token,saved))refresh("Решение сохранено. Состояние устройства проверяйте в журнале.")
            }catch(error:CancellationException){throw error
            }catch(_:Exception){if(active && generation==token)refresh("Результат запроса не подтверждён. Обновите состояние; автоматического повтора нет.")}
        }
    }
    fun decide(approve:Boolean,selected:List<String> = emptyList()){
        val v=mutable.value.view?:return
        if(approve && (!v.policy.enabled || !v.eligible || v.stale || !targets(selected) || selected.isEmpty() || selected.any{it !in v.policy.allowedTargets || it in v.startedTargets}))return
        mutate{it.decide(v.eventId,MeetingDecision(if(approve)"approve"else "disable",v.eventRevision,if(approve)v.policyScope else null,if(approve)selected else emptyList()))}
    }
    fun acknowledge(entity:String,generation:String,checked:Boolean){
        if(!checked || mutable.value.page?.leases?.none{it.entityId==entity && it.generation==generation && it.state=="unknown"}!=false)return
        mutate{it.ack(entity,MeetingAck(generation,true))}
    }
}
