package com.shadeai.app.ui

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.reminders.ReminderDelivery
import com.shadeai.app.reminders.ReminderPrefs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun ReminderSettings(){
    val context=LocalContext.current.applicationContext
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    val scope=rememberCoroutineScope()
    var enabled by remember{mutableStateOf(false)}
    var busy by remember{mutableStateOf(false)}
    var error by remember{mutableStateOf<String?>(null)}
    var exact by remember{mutableStateOf(ReminderDelivery.exactPermission(context))}
    var count by remember{mutableStateOf(0)}
    fun read(){scope.launch{
        val snapshot=withContext(Dispatchers.IO){Triple(ReminderPrefs.enabled(context),ReminderPrefs.error(context),ReminderPrefs.items(context).size)}
        enabled=snapshot.first;error=snapshot.second?:error?.takeIf{it=="settings" || it=="permission"};count=snapshot.third;exact=ReminderDelivery.exactPermission(context)
    }}
    var permissionRevision by remember{mutableStateOf<String?>(null)}
    fun toggle(on:Boolean,revision:String){
        if(busy)return
        busy=true
        scope.launch{
            try{withContext(Dispatchers.IO){ReminderDelivery.setEnabled(context,on,revision)};error=null}
            catch(_:Exception){error="settings"}
            finally{busy=false;read()}
        }
    }
    val permission=rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()){granted->
        val revision=permissionRevision;permissionRevision=null
        if(granted && revision!=null)toggle(true,revision)else error="permission"
    }
    DisposableEffect(lifecycle){
        val observer=LifecycleEventObserver{_,event->if(event==Lifecycle.Event.ON_START){read();if(ReminderPrefs.enabled(context))ReminderDelivery.checkNow(context)}}
        lifecycle.addObserver(observer);read()
        onDispose{lifecycle.removeObserver(observer)}
    }
    Text("Напоминания календаря",style=MaterialTheme.typography.titleLarge)
    Text("За 10 минут по умолчанию: срок задаёт Core. Отдельное согласие на этом телефоне. Без связи с Core уведомление не показывается; задержка более 5 минут пропускается.")
    if(!exact){
        Text("Нужен системный доступ к точным будильникам. После выдачи вернитесь и включите напоминания.")
        OutlinedButton(onClick={
            if(Build.VERSION.SDK_INT>=31)runCatching{context.startActivity(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,Uri.parse("package:${context.packageName}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))}
        }){Text("Разрешить точные будильники")}
    }
    Row{
        Switch(checked=enabled,enabled=!busy && (exact || enabled),onCheckedChange={on->
            val revision=ServerPrefs.revision(context)
            if(on && Build.VERSION.SDK_INT>=33 && !ReminderDelivery.notificationPermission(context)){
                permissionRevision=revision;permission.launch(Manifest.permission.POST_NOTIFICATIONS)
            }else toggle(on,revision)
        })
        Text(if(enabled)"Включены для текущего Core"else "Выключены")
    }
    error?.let {Text(when(it){
        "source"->"Источник календаря сменился. Выключите и включите напоминания после проверки источника."
        "permission"->"Проверьте системные разрешения, затем выключите и включите напоминания."
        "access"->"Core отклонил ключ. Проверьте подключение и включите напоминания заново."
        "unsupported"->"Core не поддерживает календарные напоминания."
        "overflow"->"Слишком много событий. Уточните календарь и включите напоминания заново."
        "format_clock"->"Проверьте часы телефона и версию Core, затем включите заново."
        else->"Не удалось сохранить настройку. Проверьте подключение."
    })}
    if(enabled){
        Text("В расписании: $count. Откройте экран повторно для обновления статуса. Android может ограничить фон после force-stop или из-за энергосбережения.")
        OutlinedButton(onClick={ReminderDelivery.checkNow(context);read()}){Text("Обновить расписание")}
    }
}
