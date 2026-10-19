package com.shadeai.app.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalWindowInfo
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.time.Instant

@Composable
fun VoiceRoute(model:VoiceViewModel,onBack:()->Unit){
    val state by model.state.collectAsStateWithLifecycle()
    val context=LocalContext.current
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    val focused=LocalWindowInfo.current.isWindowFocused
    val currentFocused by rememberUpdatedState(focused)
    var micGranted by remember{mutableStateOf(ContextCompat.checkSelfPermission(context,Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED)}
    val permission=rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()){granted->micGranted=granted;if(!granted)model.denied()}
    DisposableEffect(model,lifecycle){
        val observer=LifecycleEventObserver{_,event->when(event){
            Lifecycle.Event.ON_RESUME->{micGranted=ContextCompat.checkSelfPermission(context,Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED;if(currentFocused)model.start()}
            Lifecycle.Event.ON_PAUSE->model.close()
            else->Unit
        }}
        lifecycle.addObserver(observer)
        if(currentFocused && lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))model.start()
        onDispose{lifecycle.removeObserver(observer);model.close()}
    }
    LaunchedEffect(model,focused,lifecycle){
        if(!focused)model.close()
        else if(lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))model.start()
    }
    val buttons=ButtonDefaults.outlinedButtonColors(contentColor=MaterialTheme.colorScheme.onSurface)
    val busy=state.phase in setOf("loading","preparing","recording","recognizing","executing")
    Surface(Modifier.fillMaxSize(),color=MaterialTheme.colorScheme.background){
        LazyColumn(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing).padding(24.dp),verticalArrangement=Arrangement.spacedBy(16.dp)){
            item{Text("Голосовая команда",style=MaterialTheme.typography.headlineMedium)}
            item{OutlinedButton(onClick=onBack,colors=buttons){Text("К подключению")}}
            item{Text("Запись до 10 секунд. Звук передаётся только домашнему Core. Сначала проверьте распознанную команду на экране, затем подтвердите действие.")}
            if(!micGranted)item{OutlinedButton(onClick={permission.launch(Manifest.permission.RECORD_AUDIO)},colors=buttons){Text("Разрешить микрофон")}}
            state.page?.let{page->
                if(!page.enabled)item{Text("Голосовые команды выключены в Core.")}
                else if(!page.sttAvailable)item{Text("Локальное распознавание в Core ещё не подготовлено. Запись недоступна.")}
                if(page.targets.isNotEmpty())item{
                    Text("Разрешённые фразы",style=MaterialTheme.typography.titleMedium)
                    page.targets.forEach{target->Text("«Включи ${target.alias}» / «Выключи ${target.alias}» → ${target.entityId}")}
                }
                if(state.phase=="recording")item{Column{
                    Text("Идёт запись…")
                    OutlinedButton(onClick=model::stopRecording,colors=buttons){Text("Готово — распознать")}
                    OutlinedButton(onClick=model::cancelCapture,colors=buttons){Text("Отменить запись")}
                }}else if(state.phase in setOf("preparing","recognizing"))item{Column{
                    Text(if(state.phase=="preparing")"Подготовка микрофона…"else "Core распознаёт команду…")
                    OutlinedButton(onClick=model::cancelCapture,colors=buttons){Text("Остановить ожидание")}
                }}else item{OutlinedButton(onClick={model.record(model.revision())},enabled=micGranted && page.enabled && page.sttAvailable && !busy,colors=buttons){Text("Записать команду")}}
            }
            state.error?.let{item{Text(it,color=MaterialTheme.colorScheme.error)}}
            state.message?.let{item{Text(it)}}
            state.request?.let{request->item{Column(verticalArrangement=Arrangement.spacedBy(8.dp)){
                Text("Проверка команды",style=MaterialTheme.typography.titleLarge)
                request.transcription?.let{Text("Распознано: «$it»")}
                Text((if(request.action=="turn_on")"Включить"else "Выключить")+" ${request.alias} · ${request.entityId}")
                Text(voiceStatus(request.state))
                request.newState?.let{Text("Наблюдаемое состояние: "+when(it){"on"->"включено";"off"->"выключено";else->"недоступно"})}
                if(request.state=="pending"){
                    OutlinedButton(onClick=model::confirm,enabled=!busy && state.phase=="ready" && state.page?.enabled==true && Instant.now().isBefore(Instant.parse(request.expiresAt)),colors=buttons){Text("Подтверждаю действие")}
                    OutlinedButton(onClick=model::cancel,enabled=!busy,colors=buttons){Text("Отменить запрос")}
                }
                if(request.state in setOf("dispatching","unknown") || state.phase=="uncertain")Text("Автоматического повтора нет. Проверьте устройство и состояние запроса.")
                OutlinedButton(onClick=model::checkStatus,enabled=!busy,colors=buttons){Text("Проверить состояние запроса")}
            }}}
            item{OutlinedButton(onClick=model::refresh,enabled=!busy,colors=buttons){Text("Обновить историю")}}
            state.page?.let{page->
                item{Text("Последние запросы",style=MaterialTheme.typography.titleLarge)}
                if(page.requests.isEmpty())item{Text("Голосовых запросов пока нет.")}
                page.requests.forEach{row->item(key=row.id){Column{
                    Text("${row.alias} · ${if(row.action=="turn_on")"Включить"else "Выключить"}")
                    Text(voiceStatus(row.state))
                    OutlinedButton(onClick={model.select(row)},enabled=!busy,colors=buttons){Text("Открыть запрос")}
                }}}
            }
        }
    }
}
