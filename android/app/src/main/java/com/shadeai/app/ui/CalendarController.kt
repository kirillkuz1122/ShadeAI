package com.shadeai.app.ui

import com.shadeai.app.core.network.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import retrofit2.HttpException

fun knownCalendar(page:CoreCalendarPage):Boolean=try {
    ZoneId.of(page.timezone)
    page.lastSuccess?.let {Instant.parse(it)}
    page.total in 0..1000 && page.events.size<=50 && page.events.all {e ->
        Regex("cal_[0-9a-f]{32}").matches(e.id) && e.summary.length<=200 && (e.location?.length?:0)<=255 &&
            e.status in listOf("confirmed","tentative","cancelled","removed") && e.revision>0 &&
            !Instant.parse(e.endsAt).isBefore(Instant.parse(e.startsAt)) &&
            if(e.allDay) LocalDate.parse(e.endDate).isAfter(LocalDate.parse(e.startDate)) else e.startDate==null && e.endDate==null
    }
}catch(_:Exception){false}
fun calendarTime(e:CoreCalendarEvent,zone:String):String=try {
    val locale=Locale.forLanguageTag("ru")
    if(e.allDay){
        val first=LocalDate.parse(e.startDate);val last=LocalDate.parse(e.endDate).minusDays(1)
        val format=DateTimeFormatter.ofPattern("d MMMM uuuu",locale)
        "Весь день · ${format.format(first)}"+(if(first!=last)" — ${format.format(last)}" else "")
    }else{
        val format=DateTimeFormatter.ofPattern("d MMM, HH:mm",locale).withZone(ZoneId.of(zone))
        "${format.format(Instant.parse(e.startsAt))} — ${format.format(Instant.parse(e.endsAt))} · $zone"
    }
}catch(_:Exception){"Время не распознано"}
fun calendarStatus(status:String)=when(status){"confirmed"->"Подтверждено";"tentative"->"Предварительно";"cancelled"->"Отменено";"removed"->"Нет в текущей выборке";else->"Формат не поддерживается"}

data class CalendarState(val offset:Int=0,val inactive:Boolean=false,val page:CoreCalendarPage?=null,
    val loading:Boolean=true,val busy:Boolean=false,val error:String?=null,val message:String?=null
){override fun toString()="CalendarState(redacted)"}
class CalendarController(private val scope:CoroutineScope,private val credentials:suspend()->ResultsCredentials,
    private val revision:()->String,private val client:(ResultsCredentials)->CalendarClient,private val pollMillis:Long=30000){
    private val mutable=MutableStateFlow(CalendarState());val state=mutable.asStateFlow()
    private var active=false;private var generation=0;private var request:Job?=null
    private var sessionRevision:String?=null;private var displayRevision:String?=null
    fun start(){active=true;refresh()}
    fun close(){active=false;generation++;request?.cancel();request=null;displayRevision=null;mutable.value=mutable.value.copy(page=null,error=null,message=null,loading=true,busy=false)}
    fun settingsChanged(){sessionRevision=null;mutable.value=CalendarState();if(active)refresh()}
    fun filter(value:Boolean){mutable.value=CalendarState(inactive=value);refresh()}
    fun next(){val s=mutable.value;if(!s.loading && !s.busy && s.page!=null && s.offset+50<s.page.total){mutable.value=CalendarState(offset=s.offset+50,inactive=s.inactive);refresh()}}
    fun previous(){val s=mutable.value;if(!s.loading && !s.busy && s.offset>0){mutable.value=CalendarState(offset=(s.offset-50).coerceAtLeast(0),inactive=s.inactive);refresh()}}
    private fun valid(token:Int,saved:ResultsCredentials)=active && token==generation && saved.revision==revision()
    fun refresh(message:String?=null){
        if(!active)return
        request?.cancel();displayRevision=null;val token=++generation
        val query=mutable.value.copy(page=null,loading=true,busy=false,error=null,message=message);mutable.value=query
        request=scope.launch{
            try{
                val saved=credentials();if(!valid(token,saved))return@launch
                if(sessionRevision!=null && sessionRevision!=saved.revision){sessionRevision=saved.revision;mutable.value=CalendarState();refresh(message);return@launch}
                sessionRevision=saved.revision;require(saved.apiKey.isNotBlank());val api=client(saved)
                while(isActive && valid(token,saved)){
                    try{
                        val page=api.page(query.offset,query.inactive);check(knownCalendar(page))
                        if(!valid(token,saved))return@launch
                        displayRevision=saved.revision;mutable.value=query.copy(page=page,loading=false)
                    }catch(error:CancellationException){throw error
                    }catch(error:Exception){
                        if(!valid(token,saved))return@launch
                        mutable.value=query.copy(page=null,loading=false,error=if(error is HttpException && error.code() in listOf(401,403))"Ключ не принят. Проверьте подключение." else "Календарь недоступен или формат не поддерживается.")
                        if(error is HttpException && error.code() in listOf(401,403,404))return@launch
                    }
                    delay(pollMillis)
                }
            }catch(error:CancellationException){throw error
            }catch(_:Exception){if(active && token==generation)mutable.value=query.copy(page=null,loading=false,error="Проверьте адрес и ключ Core.")}
        }
    }
    fun sync(){
        val displayed=displayRevision
        if(!active || mutable.value.busy || displayed==null || mutable.value.page?.configured!=true)return
        request?.cancel();val token=++generation;mutable.value=mutable.value.copy(busy=true,error=null,message=null)
        request=scope.launch{
            try{
                val saved=credentials();if(!valid(token,saved))return@launch
                if(saved.revision!=displayed){refresh("Настройки Core изменились. Проверьте календарь заново.");return@launch}
                val result=client(saved).sync();if(valid(token,saved))refresh(if(result.status=="ready")"Календарь синхронизирован." else "Синхронизация не настроена.")
            }catch(error:CancellationException){throw error
            }catch(_:Exception){if(active && token==generation)refresh("Синхронизация не подтверждена. Проверьте актуальность кэша.")}
        }
    }
}
