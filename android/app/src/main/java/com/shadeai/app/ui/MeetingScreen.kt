package com.shadeai.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable
fun MeetingScreen(controller:MeetingController,onBack:()->Unit){
    val state by controller.state.collectAsStateWithLifecycle()
    val buttons=ButtonDefaults.outlinedButtonColors(contentColor=MaterialTheme.colorScheme.onSurface)
    Surface(Modifier.fillMaxSize(),color=MaterialTheme.colorScheme.background){
        LazyColumn(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing).padding(24.dp),verticalArrangement=Arrangement.spacedBy(16.dp)){
            item{Text("Режим дома для встречи",style=MaterialTheme.typography.headlineMedium)}
            item{OutlinedButton(onClick=onBack,colors=buttons){Text("К календарю")}}
            item{Text("Для подтверждённой занятой встречи до 8 часов. Выберите только переключатели «Не беспокоить». После последней пересекающейся встречи Shade выключает лишь собственное включение без обнаруженных ручных изменений. Уже включённое устройство не выключаем.")}
            item{OutlinedButton(onClick={controller.refresh()},enabled=!state.busy,colors=buttons){Text("Обновить состояние")}}
            if(state.loading)item{Text("Загрузка…")}
            state.error?.let{item{Text(it,color=MaterialTheme.colorScheme.error)}}
            state.message?.let{item{Text(it)}}
            state.view?.let {view->item{
                key(view.policyScope,view.status,view.startedTargets){
                    var selected by remember{mutableStateOf(emptyList<String>())}
                    Text(meetingStatus(view.status),style=MaterialTheme.typography.titleMedium)
                    val format=DateTimeFormatter.ofPattern("dd.MM HH:mm").withZone(ZoneId.systemDefault())
                    Text("${format.format(Instant.parse(view.startsAt))} — ${format.format(Instant.parse(view.endsAt))} · ${ZoneId.systemDefault()}")
                    if(!view.policy.enabled)Text("Режим встреч выключен в Core.")
                    if(view.stale)Text("Кэш устарел. Новое включение недоступно.")
                    if(view.targets.isNotEmpty())Text("Сохранённый выбор: ${view.targets.joinToString()}")
                    if(view.startedTargets.isNotEmpty())Text("Уже запускались: ${view.startedTargets.joinToString()}. Эта версия события повторно их не запускает.")
                    view.policy.allowedTargets.filter{it !in view.startedTargets}.forEach {target->Row{
                        Checkbox(checked=target in selected,enabled=!state.busy && view.policy.enabled && view.eligible && !view.stale,onCheckedChange={on->selected=if(on)selected+target else selected-target})
                        Text(target)
                    }}
                    OutlinedButton(onClick={controller.decide(true,selected)},enabled=!state.busy && selected.isNotEmpty() && view.policy.enabled && view.eligible && !view.stale,colors=buttons){Text("Подтверждаю выбранный режим")}
                    OutlinedButton(onClick={controller.decide(false)},enabled=!state.busy,colors=buttons){Text("Отключить для этой встречи")}
                }
            }}
            state.page?.let{page->
                item{Text("Состояние устройств",style=MaterialTheme.typography.titleLarge)}
                if(!page.policy.enabled)item{Text("Режим встреч выключен в Core.")}
                if(page.leases.isEmpty())item{Text("Устройств в режиме встречи пока нет.")}
                page.leases.forEach{lease->item(key=lease.entityId){
                    key(lease.generation,lease.updatedAt){
                        var checked by remember{mutableStateOf(false)}
                        Text(lease.entityId,style=MaterialTheme.typography.titleMedium)
                        Text(meetingStatus(lease.state));meetingReason(lease.reason)?.let{Text(it)}
                        Text("Участвующих встреч: ${lease.members.size}")
                        if(lease.state=="unknown"){
                            Row{Checkbox(checked=checked,onCheckedChange={checked=it},enabled=!state.busy);Text("Я проверил устройство и при необходимости восстановил вручную")}
                            OutlinedButton(onClick={controller.acknowledge(lease.entityId,lease.generation,checked)},enabled=checked && !state.busy,colors=buttons){Text("Закрыть неопределённый результат")}
                            Text("Это очищает блокировку; команд устройству не отправляет.")
                        }
                    }
                }}
                item{Text("Последние изменения",style=MaterialTheme.typography.titleMedium)}
                page.history.take(10).forEach{log->item(key="log-${log.id}"){Text("${log.entityId} · ${meetingStatus(log.state)}")}}
            }
        }
    }
}
