package com.shadeai.app.ui

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.view.WindowManager
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalWindowInfo
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private fun Context.ownerActivity(): Activity? = when(this) {
    is Activity -> this
    is ContextWrapper -> if(baseContext===this) null else baseContext.ownerActivity()
    else -> null
}
private fun accessTime(value: String)=runCatching {
    DateTimeFormatter.ofPattern("dd.MM HH:mm:ss").withZone(ZoneId.systemDefault()).format(Instant.parse(value))
}.getOrDefault("Время недоступно")

@Composable
fun AccessRoute(model: AccessViewModel,onBack: () -> Unit) {
    val state by model.state.collectAsStateWithLifecycle()
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    val listState=remember { LazyListState() }
    LaunchedEffect(state.grant?.id) { if(state.grant!=null) listState.scrollToItem(0) }
    val window=LocalContext.current.ownerActivity()?.window
    val focused=LocalWindowInfo.current.isWindowFocused
    val currentFocused by rememberUpdatedState(focused)
    DisposableEffect(model,lifecycle,window) {
        val flag=WindowManager.LayoutParams.FLAG_SECURE
        val alreadySecure=window?.attributes?.flags?.and(flag)==flag
        val protected=runCatching { window?.addFlags(flag); window!=null && window.attributes.flags and flag != 0 }.getOrDefault(false)
        val observer=LifecycleEventObserver { _,event -> when(event) {
            Lifecycle.Event.ON_RESUME -> if(currentFocused) model.start(protected && window!=null && window.attributes.flags and flag != 0)
            Lifecycle.Event.ON_PAUSE -> model.close()
            else -> Unit
        } }
        lifecycle.addObserver(observer)
        if(currentFocused && lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) model.start(protected)
        onDispose { model.close(); lifecycle.removeObserver(observer); if(!alreadySecure) window?.clearFlags(flag) }
    }
    LaunchedEffect(model,focused,lifecycle,window) {
        if(!focused) model.close()
        else if(lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))
            model.start(window!=null && window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE != 0)
    }
    LaunchedEffect(state.grant?.id,state.grant?.pin) {
        val grant=state.grant
        if(grant?.pin!=null) {
            while(Instant.now().isBefore(Instant.parse(grant.expiresAt))) delay(1000)
            model.hidePin()
        }
    }
    val busy=state.phase in setOf("loading","reviewing","creating","updating")
    val colors=ButtonDefaults.outlinedButtonColors(contentColor=MaterialTheme.colorScheme.onSurface)
    Surface(Modifier.fillMaxSize(),color=MaterialTheme.colorScheme.background) {
        LazyColumn(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing).padding(24.dp),state=listState,
            verticalArrangement=Arrangement.spacedBy(16.dp)) {
            item { Text("Доступ для доставки",style=MaterialTheme.typography.headlineMedium) }
            item { OutlinedButton(onClick=onBack,colors=colors) { Text("К подключению") } }
            state.grant?.let { grant -> item { Column(verticalArrangement=Arrangement.spacedBy(8.dp)) {
                Text("Доступ №${grant.notificationId} · ${grant.entityId}",style=MaterialTheme.typography.titleLarge)
                Text(accessStatus(grant.state)); Text("До ${accessTime(grant.expiresAt)}")
                grant.pin?.let { pin ->
                    Text(pin,style=MaterialTheme.typography.headlineLarge)
                    Text("PIN показывается один раз. После скрытия восстановить его нельзя.")
                    OutlinedButton(onClick=model::hidePin,colors=colors) { Text("Скрыть PIN") }
                }
                grant.newState?.let { observed -> Text("Наблюдаемое состояние: "+when(observed) { "locked"->"заперто";"unlocked"->"отперто";else->"изменяется или не подтверждено" }) }
                if(grant.state=="unknown") AccessCheck("Дверь проверил вручную; понимаю, что отзыв не запирает её",state.manualChecked,!busy,model::manualChecked)
                if(grant.state in setOf("active","unknown")) OutlinedButton(onClick=model::revoke,
                    enabled=!busy && state.phase=="idle" && (grant.state!="unknown" || state.manualChecked),colors=colors) { Text("Отозвать доступ") }
                OutlinedButton(onClick=model::checkStatus,enabled=!busy,colors=colors) { Text("Проверить состояние доступа") }
            } } }
            item { Text("Проверьте доставку самостоятельно. PIN работает один раз через домашний Core и совместимую локальную клавиатуру Shade. Встроенные PIN замка не изменяются.") }
            item { Text("Скрытие экрана убирает PIN, но не отзывает его. Отзыв не запирает уже открытую дверь.") }
            state.error?.let { item { Text(it,color=MaterialTheme.colorScheme.error) } }
            state.message?.let { item { Text(it) } }
            if(busy) item { Text("Обновление…") }
            state.page?.let { page ->
                if(!page.enabled) item { Text("Выдача доступа выключена в Core.") }
                item { Text("Результаты обработки доставки",style=MaterialTheme.typography.titleLarge) }
                if(state.rows.isEmpty()) item { Text("На этой странице подходящих доставок нет. Отметка модели сама не разрешает доступ.") }
                state.rows.forEach { row -> item(key="source-${row.id}") {
                    OutlinedButton(onClick={model.selectSource(row.id)},enabled=!busy,colors=colors) {
                        Text("Доставка №${row.id} · ${accessTime(row.timestamp)}")
                    }
                } }
                item { Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick={model.refresh((state.offset-20).coerceAtLeast(0))},enabled=!busy && state.offset>0,colors=colors) { Text("Назад") }
                    OutlinedButton(onClick={model.refresh(state.offset+20)},enabled=!busy && state.offset.toLong()+20<state.total,colors=colors) { Text("Далее") }
                } }
                state.source?.let { source -> item { Column(verticalArrangement=Arrangement.spacedBy(8.dp)) {
                    Text("Проверка доставки №${source.id}",style=MaterialTheme.typography.titleLarge)
                    Text(source.appName); Text(source.title); Text(source.text); Text(accessTime(source.timestamp))
                    Text("Выберите замок",style=MaterialTheme.typography.titleMedium)
                    page.allowedLocks.forEach { target -> OutlinedButton(onClick={model.target(target)},enabled=!busy && page.enabled,colors=colors) {
                        Text((if(state.target==target)"Выбран: " else "Выбрать: ")+target)
                    } }
                    Text("Срок с момента выдачи: ${state.minutes} мин")
                    Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                        OutlinedButton(onClick={model.minutes(state.minutes-1)},enabled=!busy && state.minutes>1,colors=colors) { Text("− минута") }
                        OutlinedButton(onClick={model.minutes(state.minutes+1)},enabled=!busy && state.minutes<15,colors=colors) { Text("+ минута") }
                    }
                    AccessCheck("Доставку и её контекст проверил",state.deliveryChecked,!busy,model::deliveryChecked)
                    AccessCheck("Разрешаю одно открытие выбранного замка по PIN",state.unlockChecked,!busy,model::unlockChecked)
                    OutlinedButton(onClick=model::create,enabled=!busy && state.phase=="idle" && page.enabled && state.target!=null && state.deliveryChecked && state.unlockChecked && page.grants.none{it.notificationId==source.id},colors=colors) { Text("Создать одноразовый PIN") }
                } } }
                item { Text("Последние доступы",style=MaterialTheme.typography.titleLarge) }
                page.grants.forEach { grant -> item(key="grant-${grant.id}") {
                    Column { Text("№${grant.notificationId} · ${grant.entityId} · ${accessStatus(grant.state)}")
                        OutlinedButton(onClick={model.selectGrant(grant.id)},enabled=!busy,colors=colors) { Text("Открыть доступ") }
                    }
                } }
            }
            item { OutlinedButton(onClick={model.refresh()},enabled=!busy,colors=colors) { Text("Обновить список доступов") } }
        }
    }
}

@Composable
private fun AccessCheck(label: String,checked: Boolean,enabled: Boolean,onChange: (Boolean) -> Unit) {
    Row { Checkbox(checked=checked,onCheckedChange=onChange,enabled=enabled); Text(label,Modifier.weight(1f)) }
}
