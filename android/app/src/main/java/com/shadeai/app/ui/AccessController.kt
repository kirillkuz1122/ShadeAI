package com.shadeai.app.ui

import com.shadeai.app.core.network.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import retrofit2.HttpException
import java.time.Instant

private val accessBusy = setOf("loading", "reviewing", "creating", "updating")
fun accessSource(row: CoreNotification, now: Instant = Instant.now()): Boolean = runCatching {
    row.id > 0 && row.title.length <= 512 && row.text.length <= 8192 && row.appName.length <= 255 &&
        row.processingStatus == "processed" && row.category == "delivery" &&
        coreProcessing(row.processedData) is CoreProcessing.Extracted &&
        row.processedData!!.jsonObject["category"]!!.jsonPrimitive.content == "delivery" &&
        !Instant.parse(row.timestamp).isAfter(now) &&
        !Instant.parse(row.timestamp).isBefore(now.minusSeconds(86400))
}.getOrDefault(false)

data class AccessState(
    val page: CoreAccess? = null, val rows: List<CoreNotification> = emptyList(),
    val total: Int = 0, val offset: Int = 0, val source: CoreNotification? = null,
    val target: String? = null, val minutes: Int = 5,
    val deliveryChecked: Boolean = false, val unlockChecked: Boolean = false,
    val manualChecked: Boolean = false, val grant: CoreAccessGrant? = null,
    val phase: String = "loading", val error: String? = null, val message: String? = null,
) { override fun toString() = "AccessState(redacted)" }

class AccessController(
    private val scope: CoroutineScope,
    private val credentials: suspend () -> ResultsCredentials,
    private val revision: () -> String,
    private val client: (ResultsCredentials) -> AccessClient,
    private val results: (ResultsCredentials) -> ResultsClient,
) {
    private val mutable = MutableStateFlow(AccessState())
    val state = mutable.asStateFlow()
    private var active = false
    private var generation = 0
    private var job: Job? = null
    private var displayed: String? = null
    private var secure = false
    private fun valid(token: Int, saved: ResultsCredentials): Boolean {
        if(active && token==generation && saved.revision!=revision()) {
            close()
            mutable.value=AccessState(phase="idle",error="Подключение изменилось. Откройте экран заново.")
            return false
        }
        return active && secure && token == generation
    }
    private fun denied(error: Exception) = error is HttpException && error.code() in setOf(401, 403)
    fun start(secureWindow: Boolean) {
        if (active && secure == secureWindow) return
        active = true; secure = secureWindow
        if (secureWindow) refresh() else mutable.value = AccessState(phase="idle", error="Защищённое окно недоступно. Доступ к выдаче кода закрыт.")
    }
    fun close() { active=false; secure=false; generation++; job?.cancel(); displayed=null; mutable.value=AccessState() }
    fun settingsChanged() { val was=active; val protected=secure; close(); if(was) start(protected) }
    fun refresh(offset: Int = mutable.value.offset, message: String? = null) {
        if (!active || !secure || mutable.value.phase in setOf("creating", "updating")) return
        job?.cancel(); val token=++generation; displayed=null
        val safeOffset=offset.coerceAtLeast(0)
        mutable.value=AccessState(offset=safeOffset, message=message)
        job=scope.launch {
            try {
                val saved=credentials(); require(saved.apiKey.isNotBlank()); if(!valid(token,saved)) return@launch
                val page=client(saved).descriptor(); check(knownAccess(page)); if(!valid(token,saved)) return@launch
                val list=results(saved).list(20,safeOffset); if(!valid(token,saved)) return@launch
                check(list.total>=0 && list.items.size<=20 && list.items.map{it.id}.distinct().size==list.items.size)
                displayed=saved.revision
                mutable.value=AccessState(page=page, rows=list.items.filter { accessSource(it) }, total=list.total,
                    offset=safeOffset, phase="idle", message=message)
            } catch(error: CancellationException) { throw error
            } catch(error: Exception) { failure(token,error,"Не удалось обновить доступ и доставки.") }
        }
    }
    fun selectSource(id: Long) {
        val before=mutable.value; val seen=displayed?:return
        if(!active || !secure || before.phase in accessBusy || before.rows.none{it.id==id}) return
        job?.cancel(); val token=++generation
        mutable.value=before.copy(source=null,target=null,grant=null,deliveryChecked=false,unlockChecked=false,
            manualChecked=false,phase="reviewing",error=null,message=null)
        job=scope.launch {
            try {
                val saved=credentials(); if(!valid(token,saved)) return@launch
                if(saved.revision!=seen) { reset("Подключение изменилось. Проверьте условия заново."); return@launch }
                val source=results(saved).detail(id); if(!valid(token,saved)) return@launch
                check(source.id==id && accessSource(source))
                mutable.value=mutable.value.copy(source=source,phase="idle")
            } catch(error: CancellationException) { throw error
            } catch(error: Exception) { failure(token,error,"Доставка недоступна или не подходит для выдачи доступа.") }
        }
    }
    fun target(value: String) { val s=mutable.value; if(s.phase in accessBusy || s.page?.allowedLocks?.contains(value)!=true) return
        mutable.value=s.copy(target=value,deliveryChecked=false,unlockChecked=false,grant=null,manualChecked=false) }
    fun minutes(value: Int) { val s=mutable.value; if(s.phase in accessBusy || value !in 1..15) return
        mutable.value=s.copy(minutes=value,deliveryChecked=false,unlockChecked=false,grant=null,manualChecked=false) }
    fun deliveryChecked(value: Boolean) { if(mutable.value.phase=="idle") mutable.value=mutable.value.copy(deliveryChecked=value) }
    fun unlockChecked(value: Boolean) { if(mutable.value.phase=="idle") mutable.value=mutable.value.copy(unlockChecked=value) }
    fun manualChecked(value: Boolean) { if(mutable.value.phase=="idle") mutable.value=mutable.value.copy(manualChecked=value) }
    fun hidePin() { mutable.value=mutable.value.copy(grant=mutable.value.grant?.copy(pin=null)) }
    private fun reset(message: String) { mutable.value=AccessState(phase="idle"); refresh(0,message) }
    private fun failure(token: Int, error: Exception, text: String, uncertain: Boolean=false) {
        if(!active || token!=generation) return
        if(denied(error)) { displayed=null; mutable.value=AccessState(phase="idle",error="Ключ не принят. Проверьте подключение.") }
        else mutable.value=mutable.value.copy(source=null,target=null,deliveryChecked=false,unlockChecked=false,
            manualChecked=false,grant=mutable.value.grant?.copy(pin=null),phase=if(uncertain)"uncertain"else"idle",error=text)
    }
    fun create() {
        val s=mutable.value; val page=s.page?:return; val source=s.source?:return; val target=s.target?:return
        val seen=displayed?:return
        if(!active || !secure || s.phase!="idle" || !page.enabled || !s.deliveryChecked || !s.unlockChecked ||
            !accessSource(source) || target !in page.allowedLocks || s.grant!=null ||
            page.grants.any{it.notificationId==source.id}) return
        job?.cancel(); val token=++generation
        mutable.value=s.copy(phase="creating",error=null,message=null,deliveryChecked=false,unlockChecked=false)
        job=scope.launch {
            try {
                val saved=credentials(); if(!valid(token,saved)) return@launch
                if(saved.revision!=seen) { reset("Подключение изменилось. Согласие сброшено."); return@launch }
                val current=client(saved).descriptor(); if(!valid(token,saved)) return@launch
                check(knownAccess(current))
                if(!current.enabled || current.policyScope!=page.policyScope || target !in current.allowedLocks) {
                    reset("Условия Core изменились. Проверьте их заново."); return@launch
                }
                val actual=results(saved).detail(source.id); if(!valid(token,saved)) return@launch
                if(actual!=source || !accessSource(actual)) { reset("Доставка изменилась. Согласие сброшено."); return@launch }
                val grant=client(saved).create(AccessCreation(source.id,target,s.minutes,page.policyScope,true,true))
                if(!valid(token,saved)) return@launch
                check(knownAccessGrant(grant,allowPin=true) && grant.notificationId==source.id &&
                    grant.entityId==target && grant.policyScope==page.policyScope && grant.durationMinutes==s.minutes)
                mutable.value=mutable.value.copy(page=current.copy(grants=(listOf(grant.copy(pin=null))+current.grants.filter{it.id!=grant.id}).take(50)),grant=grant,phase="idle",source=null,target=null,
                    message=if(grant.pin==null)"Доступ уже создавался. PIN повторно не показывается."else"PIN виден только сейчас. Скрытие экрана не отзывает код.")
            } catch(error: CancellationException) { throw error
            } catch(error: Exception) { failure(token,error,"Результат выдачи не подтверждён. Обновите список и отзовите доступ при необходимости. Автоповтора нет.",true) }
        }
    }
    fun selectGrant(id: String) {
        if(!active || mutable.value.phase in accessBusy) return
        val row=mutable.value.page?.grants?.firstOrNull{it.id==id}?:return
        mutable.value=mutable.value.copy(grant=row,source=null,target=null,deliveryChecked=false,
            unlockChecked=false,manualChecked=false,phase="idle",error=null,message=null)
        update(false)
    }
    fun checkStatus()=update(false)
    fun revoke()=update(true)
    private fun update(revoke: Boolean) {
        val s=mutable.value; val grant=s.grant?:return; val seen=displayed?:return
        if(!active || !secure || s.phase in accessBusy) return
        if(revoke && (s.phase!="idle" || grant.state !in setOf("active","unknown") ||
                    grant.state=="unknown" && !s.manualChecked)) return
        job?.cancel(); val token=++generation
        mutable.value=s.copy(grant=grant.copy(pin=null),manualChecked=false,phase="updating",error=null,message=null)
        job=scope.launch {
            try {
                val saved=credentials(); if(!valid(token,saved)) return@launch
                if(saved.revision!=seen) { reset("Подключение изменилось. Проверьте доступ заново."); return@launch }
                val result=if(revoke) client(saved).revoke(grant.id,AccessRevocation(grant.state=="unknown" && s.manualChecked))
                    else client(saved).state(grant.id)
                if(!valid(token,saved)) return@launch
                check(knownAccessGrant(result) && result.id==grant.id && result.notificationId==grant.notificationId &&
                    result.entityId==grant.entityId && result.policyScope==grant.policyScope)
                mutable.value=mutable.value.copy(page=mutable.value.page?.let{it.copy(grants=(listOf(result)+it.grants.filter{row->row.id!=result.id}).take(50))},grant=result,phase="idle")
            } catch(error: CancellationException) { throw error
            } catch(error: Exception) { failure(token,error,"Состояние доступа не подтверждено. Обновите список; проверьте дверь вручную.",true) }
        }
    }
}
