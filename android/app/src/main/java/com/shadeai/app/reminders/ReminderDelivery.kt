package com.shadeai.app.reminders

import android.Manifest
import android.annotation.SuppressLint
import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.*
import com.shadeai.app.MainActivity
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.core.network.CoreReminder
import com.shadeai.app.core.network.ShadeApi
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import retrofit2.HttpException
import java.time.Instant
import java.util.concurrent.TimeUnit

object ReminderDelivery {
    private const val PERIODIC="shade-calendar-reminders-periodic"
    private const val NOW="shade-calendar-reminders-now"
    private const val RETRY="shade-calendar-reminder-retry:"
    private const val CHANNEL="shade_calendar_reminders"
    const val OPEN_ACTION="com.shadeai.app.OPEN_CALENDAR"
    const val ALARM_ACTION="com.shadeai.app.CALENDAR_ALARM"
    private val mutex=Mutex()
    internal val scope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
    fun notificationPermission(c:Context)=NotificationManagerCompat.from(c).areNotificationsEnabled() &&
        (Build.VERSION.SDK_INT<33 || ContextCompat.checkSelfPermission(c,Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED) &&
        c.getSystemService(NotificationManager::class.java).getNotificationChannel(CHANNEL)?.importance!=NotificationManager.IMPORTANCE_NONE
    fun exactPermission(c:Context)=Build.VERSION.SDK_INT<31 || c.getSystemService(AlarmManager::class.java).canScheduleExactAlarms()
    private fun intent(c:Context,revision:String,id:String)=Intent(c,ReminderAlarmReceiver::class.java)
        .setAction(ALARM_ACTION).setData(Uri.Builder().scheme("shade-reminder").authority(revision).appendPath(id).build())
    private fun pending(c:Context,revision:String,id:String)=PendingIntent.getBroadcast(c,0,intent(c,revision,id),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    private fun cancelAlarms(c:Context){
        val revision=c.getSharedPreferences("shade_calendar_reminders",Context.MODE_PRIVATE).getString("revision",null)?:return
        ReminderPrefs.items(c).forEach {val pi=pending(c,revision,it.id);c.getSystemService(AlarmManager::class.java).cancel(pi);pi.cancel()}
    }
    private fun cancelNotifications(c:Context){
        val manager=c.getSystemService(NotificationManager::class.java)
        manager.activeNotifications.filter{it.tag?.startsWith("shade-reminder:")==true}.forEach{manager.cancel(it.tag,it.id)}
    }
    suspend fun setEnabled(c:Context,on:Boolean,revision:String)=mutex.withLock {
        require(revision==ServerPrefs.revision(c))
        if(on){require(notificationPermission(c)&&exactPermission(c));require(ServerPrefs.load(c).apiKey.isNotBlank())}
        cancelAlarms(c);cancelNotifications(c)
        ReminderPrefs.set(c,on,revision)
        WorkManager.getInstance(c).apply {cancelUniqueWork(NOW);cancelAllWorkByTag(RETRY);if(!on)cancelUniqueWork(PERIODIC)}
        if(on)start(c)
    }
    fun start(c:Context){
        if(!ReminderPrefs.enabled(c))return
        WorkManager.getInstance(c).enqueueUniquePeriodicWork(PERIODIC,ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<ReminderWorker>(15,TimeUnit.MINUTES).build())
        checkNow(c)
    }
    fun checkNow(c:Context){
        // Старые alarms при смене Core также отменяются внутри refresh.
        WorkManager.getInstance(c).enqueueUniqueWork(NOW,ExistingWorkPolicy.KEEP,OneTimeWorkRequestBuilder<ReminderWorker>().build())
    }
    @SuppressLint("ScheduleExactAlarm")
    private fun arm(c:Context,revision:String,item:CoreReminder,server:Instant=Instant.now()){
        if(!exactPermission(c)||!ReminderPrefs.enabled(c,revision)||ServerPrefs.revision(c)!=revision)return
        val at=maxOf(System.currentTimeMillis()+1000,System.currentTimeMillis()+java.time.Duration.between(server,Instant.parse(item.dueAt)).toMillis()+1000)
        c.getSystemService(AlarmManager::class.java).setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,at,pending(c,revision,item.id))
    }
    suspend fun refresh(c:Context)=mutex.withLock {
        val revision=ServerPrefs.revision(c)
        if(!ReminderPrefs.enabled(c,revision)){
            cancelAlarms(c);cancelNotifications(c);return@withLock
        }
        if(ReminderPrefs.error(c)!=null)return@withLock
        if(!notificationPermission(c)||!exactPermission(c)){
            cancelAlarms(c);ReminderPrefs.pause(c,"permission");return@withLock
        }
        try {
            val saved=ServerPrefs.load(c)
            if(saved.apiKey.isBlank() || ServerPrefs.revision(c)!=revision || !ReminderPrefs.enabled(c,revision))return@withLock
            val page=ShadeApi.create(saved.baseUrl,saved.apiKey).reminders()
            val items=validateReminders(page,Instant.now())
            if(ServerPrefs.revision(c)!=revision || !ReminderPrefs.enabled(c,revision))return@withLock
            if(ReminderPrefs.source(c)?.let{it!=page.sourceId}==true){
                cancelAlarms(c);cancelNotifications(c);ReminderPrefs.pause(c,"source");return@withLock
            }
            if(!page.enabled || !page.configured){cancelAlarms(c);ReminderPrefs.save(c,page.sourceId,emptyList());return@withLock}
            if(page.stale)return@withLock
            cancelAlarms(c)
            if(page.overflow){ReminderPrefs.pause(c,"overflow");return@withLock}
            val next=if(page.enabled && page.configured)items.filter{reminderReceipt(it) !in ReminderPrefs.receipts(c)}else emptyList()
            ReminderPrefs.save(c,page.sourceId,next)
            next.forEach {arm(c,revision,it,Instant.parse(page.serverTime))}
        }catch(error:CancellationException){throw error
        }catch(error:HttpException){if(error.code() in listOf(401,403,404)){
            cancelAlarms(c);ReminderPrefs.pause(c,if(error.code()==404)"unsupported"else "access")
        }
        }catch(_:IllegalArgumentException){cancelAlarms(c);ReminderPrefs.pause(c,"format_clock")
        }catch(_:Exception){/* Кэш не подтверждает событие: alarm всё равно проверит Core. */}
    }
    internal fun retry(c:Context,revision:String,id:String){
        if(!ReminderPrefs.enabled(c,revision)||ServerPrefs.revision(c)!=revision)return
        val item=ReminderPrefs.items(c).find{it.id==id}?:return
        if(!Instant.now().plusSeconds(35).isBefore(Instant.parse(item.expiresAt)))return
        WorkManager.getInstance(c).enqueueUniqueWork(RETRY+id,ExistingWorkPolicy.REPLACE,
            OneTimeWorkRequestBuilder<ReminderWorker>().setInputData(workDataOf("id" to id,"revision" to revision))
                .setInitialDelay(30,TimeUnit.SECONDS).addTag(RETRY).build())
    }
    @SuppressLint("MissingPermission")
    suspend fun fire(c:Context,revision:String,id:String)=mutex.withLock {
        if(ServerPrefs.revision(c)!=revision || !ReminderPrefs.enabled(c,revision) || ReminderPrefs.error(c)!=null ||
            !notificationPermission(c)||!exactPermission(c))return@withLock
        val scheduled=ReminderPrefs.items(c).find{it.id==id}?:return@withLock
        if(!Instant.now().minusSeconds(60).isBefore(Instant.parse(scheduled.expiresAt))||reminderReceipt(scheduled) in ReminderPrefs.receipts(c))return@withLock
        try{
            val saved=ServerPrefs.load(c)
            if(saved.apiKey.isBlank() || ServerPrefs.revision(c)!=revision || !ReminderPrefs.enabled(c,revision))return@withLock
            val page=withTimeout(5500){ShadeApi.create(saved.baseUrl,saved.apiKey).reminder(id)}
            val item=validateReminders(page,Instant.now()).single()
            require(item.id==id && item.eventId==scheduled.eventId && item.eventRevision==scheduled.eventRevision && item.dueAt==scheduled.dueAt)
            if(ServerPrefs.revision(c)!=revision || !ReminderPrefs.enabled(c,revision) || page.sourceId!=ReminderPrefs.source(c) ||
                !notificationPermission(c)||!exactPermission(c))return@withLock
            if(!reminderMayShow(page,item,Instant.parse(page.serverTime))){
                if(!item.due)arm(c,revision,item,Instant.parse(page.serverTime))
                return@withLock
            }
            val manager=c.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(CHANNEL,"Календарь Shade",NotificationManager.IMPORTANCE_DEFAULT))
            val open=PendingIntent.getActivity(c,1,Intent(c,MainActivity::class.java).setAction(OPEN_ACTION)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            val notification=NotificationCompat.Builder(c,CHANNEL).setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("Напоминание Shade").setContentText("Откройте календарь Shade для подробностей.")
                .setContentIntent(open).setAutoCancel(true).setOnlyAlertOnce(true).build()
            NotificationManagerCompat.from(c).notify("shade-reminder:$revision:${reminderReceipt(item)}",0,notification)
            ReminderPrefs.receipt(c,item)
        }catch(_:TimeoutCancellationException){retry(c,revision,id)
        }catch(error:CancellationException){throw error
        }catch(error:HttpException){if(error.code()!=404 && error.code()!=401 && error.code()!=403)retry(c,revision,id)
        }catch(_:IllegalArgumentException){/* Неподтверждённый формат не показываем. */
        }catch(_:Exception){retry(c,revision,id)}
    }
}

class ReminderWorker(c:Context,p:WorkerParameters):CoroutineWorker(c,p){
    override suspend fun doWork():Result {
        val id=inputData.getString("id");val revision=inputData.getString("revision")
        if(id!=null && revision!=null)ReminderDelivery.fire(applicationContext,revision,id)
        else ReminderDelivery.refresh(applicationContext)
        return Result.success()
    }
}
class ReminderAlarmReceiver:BroadcastReceiver(){
    override fun onReceive(c:Context,intent:Intent){
        if(intent.action!=ReminderDelivery.ALARM_ACTION)return
        val uri=intent.data?:return
        if(uri.scheme!="shade-reminder")return
        val revision=uri.authority?:return;val id=uri.lastPathSegment?:return
        val pending=goAsync()
        ReminderDelivery.scope.launch{try{withTimeout(8000){ReminderDelivery.fire(c.applicationContext,revision,id)}}catch(_:TimeoutCancellationException){ReminderDelivery.retry(c,revision,id)}finally{pending.finish()}}
    }
}
class ReminderRecoveryReceiver:BroadcastReceiver(){
    override fun onReceive(c:Context,intent:Intent){
        if(intent.action in setOf(Intent.ACTION_BOOT_COMPLETED,Intent.ACTION_MY_PACKAGE_REPLACED,Intent.ACTION_TIME_CHANGED,
                "android.app.action.SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED") && ReminderPrefs.enabled(c))ReminderDelivery.start(c)
    }
}
