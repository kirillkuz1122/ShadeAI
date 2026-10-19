package com.shadeai.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle

@Composable
fun CalendarRoute(model:CalendarViewModel,onBack:()->Unit){
    val state by model.state.collectAsStateWithLifecycle()
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    DisposableEffect(model,lifecycle){
        val observer=LifecycleEventObserver{_,event->when(event){Lifecycle.Event.ON_START->model.start();Lifecycle.Event.ON_STOP->model.close();else->Unit}}
        lifecycle.addObserver(observer)
        if(lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED))model.start()
        onDispose{lifecycle.removeObserver(observer);model.close()}
    }
    val buttons=ButtonDefaults.outlinedButtonColors(contentColor=MaterialTheme.colorScheme.onSurface)
    Surface(Modifier.fillMaxSize(),color=MaterialTheme.colorScheme.background){
        LazyColumn(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing).padding(24.dp),verticalArrangement=Arrangement.spacedBy(16.dp)){
            item{Text("Локальный календарь",style=MaterialTheme.typography.headlineMedium)}
            item{OutlinedButton(onClick=onBack,colors=buttons){Text("Назад к подключению")}}
            item{Text("События из Core. Режим встречи и доставка напоминаний включаются отдельно.")}
            item{Row{Checkbox(checked=state.inactive,onCheckedChange=model::filter);Text("Показывать отменённые и исчезнувшие")}}
            item{Column(verticalArrangement=Arrangement.spacedBy(8.dp)){
                OutlinedButton(onClick=model::refresh,enabled=!state.busy,colors=buttons){Text("Обновить")}
                OutlinedButton(onClick=model::sync,enabled=!state.busy && state.page?.configured==true,colors=buttons){Text("Синхронизировать")}
            }}
            state.error?.let{item{Text(it,color=MaterialTheme.colorScheme.error)}}
            state.message?.let{item{Text(it)}}
            if(state.loading)item{Text("Загрузка…")}
            val page=state.page
            if(page!=null){
                if(!page.configured)item{Text("Локальный календарь ещё не подключён.")}
                if(page.configured && page.stale)item{Text("Кэш устарел или обновляется. События могут отличаться от календаря.")}
                if(page.configured){
                    item{Text("Часовой пояс: ${page.timezone}")}
                    if(page.events.isEmpty())item{Text("В этом окне событий нет.")}
                    items(page.events,key={it.id}){event->
                        HorizontalDivider()
                        Text(event.summary.ifBlank{"Событие без названия"},style=MaterialTheme.typography.titleMedium)
                        Text(calendarTime(event,page.timezone))
                        event.location?.let{Text(it)}
                        Text(calendarStatus(event.status)+(if(event.busy)" · Время занято" else ""))
                    }
                    item{Text(if(page.total==0)"0 записей" else "${state.offset+1}–${minOf(state.offset+50,page.total)} из ${page.total}")}
                    item{Row(horizontalArrangement=Arrangement.spacedBy(8.dp)){
                        OutlinedButton(onClick=model::previous,enabled=state.offset>0 && !state.loading && !state.busy,colors=buttons){Text("Ранее")}
                        OutlinedButton(onClick=model::next,enabled=state.offset+50<page.total && !state.loading && !state.busy,colors=buttons){Text("Далее")}
                    }}
                }
            }
        }
    }
}
