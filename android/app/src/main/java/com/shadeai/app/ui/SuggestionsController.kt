package com.shadeai.app.ui

import com.shadeai.app.core.network.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import retrofit2.HttpException

data class SuggestionsState(val offset: Int = 0, val hintAfterId:Long=0, val historyId: String? = null,
    val page: CoreRulesPage? = null, val hints: CoreHintFeed? = null, val history: CoreRule? = null,
    val loading: Boolean = true, val busy: Boolean = false, val error: String? = null, val message: String? = null,
) { override fun toString() = "SuggestionsState(redacted)" }

class SuggestionsController(private val scope: CoroutineScope,
    private val credentials: suspend () -> ResultsCredentials, private val revision: () -> String,
    private val client: (ResultsCredentials) -> SuggestionsClient, private val pollMillis: Long = 10000,
) {
    private val mutable=MutableStateFlow(SuggestionsState())
    val state=mutable.asStateFlow()
    private var request: Job?=null
    private var generation=0
    private var active=false
    private var displayRevision:String?=null
    private var sessionRevision:String?=null
    private var feedId:String?=null
    fun start() {active=true; refresh()}
    fun close() {
        active=false;displayRevision=null;generation++;request?.cancel();request=null
        mutable.value=mutable.value.copy(page=null,hints=null,history=null,loading=true,busy=false,error=null,message=null)
    }
    fun settingsChanged() {displayRevision=null;sessionRevision=null;feedId=null;mutable.value=SuggestionsState();if(active)refresh()}
    fun history(id:String?) {mutable.value=mutable.value.copy(historyId=id);refresh()}
    fun nextHints(){val s=mutable.value;val h=s.hints?:return;if(!s.loading && !s.busy && h.nextId<h.latestId && h.nextId>s.hintAfterId){mutable.value=s.copy(hintAfterId=h.nextId);refresh()}}
    fun next() {val s=mutable.value;if(!s.loading && !s.busy && s.page != null && s.offset+20<s.page.total){mutable.value=SuggestionsState(offset=s.offset+20);refresh()}}
    fun previous() {val s=mutable.value;if(!s.loading && !s.busy && s.offset>0){mutable.value=SuggestionsState(offset=(s.offset-20).coerceAtLeast(0));refresh()}}
    private fun valid(token:Int,saved:ResultsCredentials)=active && token==generation && saved.revision==revision()
    fun refresh(message:String?=mutable.value.message) {
        if(!active)return
        request?.cancel();displayRevision=null;val token=++generation
        val query=mutable.value.copy(page=null,hints=null,history=null,loading=true,busy=false,error=null,message=message)
        mutable.value=query
        request=scope.launch {
            try {
                val saved=credentials();if(!valid(token,saved))return@launch
                if(sessionRevision!=null && sessionRevision!=saved.revision){sessionRevision=saved.revision;feedId=null;mutable.value=SuggestionsState();refresh(message);return@launch}
                sessionRevision=saved.revision
                require(saved.apiKey.isNotBlank());val api=client(saved)
                while(isActive && valid(token,saved)) {
                    try {
                        val page=api.list(query.offset);val hints=api.hints(query.hintAfterId);val history=query.historyId?.let {api.detail(it)}
                        check(page.automations.size<=20 && page.total>=0 && page.allowedTargets.size<=20 && page.allowedTargets.all(::allowedLight))
                        check(hints.hints.size<=20 && hints.latestId>=0 && hints.nextId>=0 && hints.hints.all {it.id>0 && it.notificationId>0})
                        if(!valid(token,saved))return@launch
                        if(query.hintAfterId>hints.latestId || (feedId!=null && feedId!=hints.feedId)){feedId=hints.feedId;mutable.value=mutable.value.copy(hintAfterId=0);refresh();return@launch}
                        feedId=hints.feedId
                        displayRevision=saved.revision
                        mutable.value=query.copy(page=page,hints=hints,history=history,loading=false,busy=false,error=null,message=message)
                    } catch(error:CancellationException){throw error
                    } catch(error:Exception){
                        if(!valid(token,saved))return@launch
                        mutable.value=query.copy(page=null,hints=null,history=null,loading=false,busy=false,error=errorMessage(error))
                        if(error is HttpException && error.code() in listOf(401,403,404))return@launch
                    }
                    delay(pollMillis)
                }
            } catch(error:CancellationException){throw error
            } catch(_:Exception){if(active && token==generation) mutable.value=query.copy(page=null,hints=null,history=null,loading=false,error="Проверьте сохранённый адрес и ключ Core.")}
        }
    }
    fun decide(row:CoreRule,kind:String,target:String?=null) {
        if(!knownRule(row) || kind !in listOf("accept","reject","disable"))return
        if(kind=="accept" && (!row.sourceCurrent || target == null || target !in mutable.value.page?.allowedTargets.orEmpty()))return
        mutate {api->api.decide(row.id,RuleDecision(kind,row.version,if(kind=="accept")target else null));
            when(kind){"accept"->"Выбранный сценарий подтверждён.";"reject"->"Предложение отклонено.";else->"Сценарий выключен."}}
    }
    fun updateSuggestions()=mutate(requireView=false) {api->api.refresh();"Предложения обновлены."}
    private fun mutate(requireView:Boolean=true,work:suspend (SuggestionsClient)->String) {
        if(!active || mutable.value.busy)return
        val viewed=displayRevision
        if(requireView && viewed==null)return
        request?.cancel();val token=++generation;mutable.value=mutable.value.copy(busy=true,error=null,message=null)
        request=scope.launch {
            try {
                val saved=credentials();if(!valid(token,saved))return@launch
                if(requireView && saved.revision!=viewed){refresh("Настройки Core изменились. Проверьте предложение заново.");return@launch}
                val result=work(client(saved));if(valid(token,saved))refresh(result)
            } catch(error:CancellationException){throw error
            } catch(error:Exception){if(active && token==generation)refresh(errorMessage(error))}
        }
    }
    private fun errorMessage(error:Exception)=when((error as? HttpException)?.code()) {
        401,403->"Ключ не принят. Проверьте подключение."
        409->"Условия изменились или устарели. Проверьте предложение заново."
        else->"Ответ Core не подтверждён. Обновите список перед повтором."
    }
}
