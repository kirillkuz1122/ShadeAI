package com.shadeai.app.ui

import android.Manifest
import android.os.Build
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.shadeai.app.core.network.CoreRule
import com.shadeai.app.hints.HintDelivery

@Composable
fun SuggestionsRoute(model:SuggestionsViewModel,onBack:()->Unit,onContext:(Long)->Unit) {
    val state by model.state.collectAsStateWithLifecycle()
    val hints by model.hintSettings.collectAsStateWithLifecycle()
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    val context=LocalContext.current
    var permissionRevision by remember {mutableStateOf<String?>(null)}
    val permission=rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()){granted->
        val revision=permissionRevision;permissionRevision=null
        if(granted && revision!=null)model.setHints(true,revision) else if(!granted)model.permissionDenied()
    }
    DisposableEffect(model,lifecycle){
        val observer=LifecycleEventObserver {_,event->when(event){
            Lifecycle.Event.ON_START->model.start();Lifecycle.Event.ON_STOP->model.close();else->Unit}}
        lifecycle.addObserver(observer)
        if(lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED))model.start()
        onDispose{lifecycle.removeObserver(observer);model.close()}
    }
    BackHandler(state.historyId!=null){model.history(null)}
    SuggestionsScreen(state,hints,model::update,model::history,model::decide,model::next,model::previous,
        onBack,onContext,onNextHints=model::nextHints,onHintToggle={enabled->
            val revision=model.revision()
            if(enabled && Build.VERSION.SDK_INT>=33 && !HintDelivery.permission(context)){
                permissionRevision=revision;permission.launch(Manifest.permission.POST_NOTIFICATIONS)
            }else model.setHints(enabled,revision)
        },onCheckHints=model::checkHints)
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SuggestionsScreen(state:SuggestionsState,hints:HintSettingsState,refresh:()->Unit,history:(String?)->Unit,
    decide:(CoreRule,String,String?)->Unit,next:()->Unit,previous:()->Unit,onBack:()->Unit,onContext:(Long)->Unit,
    onNextHints:()->Unit,onHintToggle:(Boolean)->Unit,onCheckHints:()->Unit) {
    val buttons=ButtonDefaults.outlinedButtonColors(contentColor=MaterialTheme.colorScheme.onSurface)
    Surface(Modifier.fillMaxSize(),color=MaterialTheme.colorScheme.background){
        LazyColumn(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing),contentPadding=PaddingValues(24.dp),
            verticalArrangement=Arrangement.spacedBy(16.dp)){
            item {
                OutlinedButton(onClick=onBack,colors=buttons){Text("К подключению")}
                Text("Сценарии и подсказки",style=MaterialTheme.typography.headlineLarge)
                OutlinedButton(onClick=refresh,colors=buttons,enabled=!state.loading && !state.busy){Text("Обновить предложения")}
                if(state.loading || state.busy)LinearProgressIndicator(Modifier.fillMaxWidth())
                state.error?.let {Text(it)};state.message?.let {Text(it)}
            }
            if(state.page?.automations?.isEmpty()==true)item{Text("Предложений пока нет. Нужен профиль присутствия с достаточной историей.")}
            items(state.page?.automations.orEmpty(),key={it.id}){row->
                if(!knownRule(row))Text("Формат предложения не поддерживается. Обновите клиент.")
                else RuleCard(row,state.page?.allowedTargets.orEmpty(),state.busy,decide,{history(if(state.historyId==row.id)null else row.id)})
            }
            state.history?.let {row->item{
                Text("История решений",style=MaterialTheme.typography.titleMedium)
                row.history.take(20).forEach {Text(decisionLabel(it.decision))}
                OutlinedButton(onClick={history(null)},colors=buttons){Text("Закрыть историю")}
            }}
            item {FlowRow(horizontalArrangement=Arrangement.spacedBy(8.dp)){
                OutlinedButton(onClick=previous,colors=buttons,enabled=state.offset>0 && !state.busy && !state.loading){Text("Более новые")}
                OutlinedButton(onClick=next,colors=buttons,enabled=state.page?.let{state.offset+20<it.total}==true && !state.busy && !state.loading){Text("Более ранние")}
            }}
            item {
                HorizontalDivider();Text("Локальные подсказки",style=MaterialTheme.typography.titleLarge)
                Text("Уведомления только после включения. Проверка примерно раз в 15 минут; Android может задерживать её.")
                Row(horizontalArrangement=Arrangement.spacedBy(12.dp)){
                    Switch(checked=hints.enabled,onCheckedChange=onHintToggle,enabled=!hints.busy)
                    Text(if(hints.enabled)"Новые подсказки включены" else "Системные подсказки выключены")
                }
                hints.error?.let {Text(it)}
                if(hints.enabled)OutlinedButton(onClick=onCheckHints,colors=buttons){Text("Проверить подсказки")}
                if(state.hints?.hints?.isEmpty()==true)Text("Новых подсказок пока нет.")
            }
            if(state.hints?.let {it.nextId<it.latestId}==true)item{OutlinedButton(onClick=onNextHints,colors=buttons){Text("Следующие подсказки")}}
            items(state.hints?.hints.orEmpty(),key={it.id}){hint->
                Column{
                    Text(if(hint.kind=="arrival_delivery")"Вы дома. В Core есть событие доставки." else "Подсказка нового типа. Обновите клиент.")
                    OutlinedButton(onClick={onContext(hint.notificationId)},colors=buttons){Text("Открыть контекст Core")}
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RuleCard(row:CoreRule,targets:List<String>,busy:Boolean,decide:(CoreRule,String,String?)->Unit,history:()->Unit) {
    var selected by remember(row.id,row.version){mutableStateOf<String?>(null)}
    val verb=if(row.trigger.kind=="arrival_home")"Включать" else "Выключать"
    val buttons=ButtonDefaults.outlinedButtonColors(contentColor=MaterialTheme.colorScheme.onSurface)
    OutlinedCard(Modifier.fillMaxWidth(),border=BorderStroke(1.dp,MaterialTheme.colorScheme.outline),
        colors=CardDefaults.outlinedCardColors(containerColor=MaterialTheme.colorScheme.surface,contentColor=MaterialTheme.colorScheme.onSurface)){
        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(12.dp)){
            Text(ruleStatus(row.status),style=MaterialTheme.typography.labelMedium)
            Text(row.name,style=MaterialTheme.typography.titleLarge)
            Text("${row.trigger.windowStart}–${row.trigger.windowEnd} · ${row.trigger.timezone}")
            Text("Совпало ${row.evidence.supportDays} из ${row.evidence.eligibleDays} дней. Регулярность ${(row.confidence*100).toInt()}% — оценка алгоритма, не вероятность.")
            if(!row.sourceCurrent)Text("Профиль изменился или устарел. Обновите предложения.")
            row.action?.let {Text("$verb: ${it.entityId}")}
            Text(if(row.executorStatus=="not_implemented")"Исполнитель ещё не подключён. Команды устройствам не отправляются." else if(row.executorStatus=="disabled")"Исполнение выключено в настройках Core." else "Решение применяется только к условиям, показанным в Core. Статус исполнителя проверьте на сервере.")
            if(row.status!="accepted"){
                Text("Светильник для сценария")
                row.executionPolicy?.let { policy ->
                Text("Общее присутствие: ${policy.homeEntity ?: "не выбрано"}. Отмена до отправки: ${policy.cancelSeconds} с; cooldown: ${policy.cooldownSeconds} с. Изменение этих условий требует нового подтверждения.")
            }
            if(targets.isEmpty())Text("Разрешённые светильники пока не заданы в настройках Core.")
                targets.filter(::allowedLight).forEach {target->FilterChip(selected=selected==target,
                    onClick={selected=target},enabled=!busy && row.sourceCurrent,label={Text(target)})}
                OutlinedButton(onClick={decide(row,"accept",selected)},colors=buttons,
                    enabled=!busy && row.sourceCurrent && selected!=null && selected in targets){Text(if(selected==null)"Разрешить сценарий" else "Разрешить: ${verb.lowercase()} $selected")}
                if(row.status!="rejected")OutlinedButton(onClick={decide(row,"reject",null)},colors=buttons,enabled=!busy){Text("Отклонить")}
            }else OutlinedButton(onClick={decide(row,"disable",null)},colors=buttons,enabled=!busy){Text("Выключить сценарий")}
            TextButton(onClick=history){Text("История решений")}
        }
    }
}
