package com.shadeai.app.hints

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.*
import com.shadeai.app.MainActivity
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.core.network.ShadeApi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import retrofit2.HttpException
import java.time.Instant
import java.util.concurrent.TimeUnit

object HintDelivery {
    internal val mutex=Mutex()
    private const val PERIODIC="shade-local-hints-periodic"
    private const val NOW="shade-local-hints-now"
    const val CHANNEL="shade_local_hints"
    const val OPEN_ACTION="com.shadeai.app.OPEN_HINTS"
    fun permission(context:Context)=NotificationManagerCompat.from(context).areNotificationsEnabled() &&
        (Build.VERSION.SDK_INT<33 || ContextCompat.checkSelfPermission(context,Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED)
    suspend fun setEnabled(context:Context,enabled:Boolean,revision:String) {
        val manager=WorkManager.getInstance(context)
        if(!enabled){manager.cancelUniqueWork(PERIODIC);manager.cancelUniqueWork(NOW)}
        mutex.withLock {
            if(enabled) {
                require(permission(context))
                require(ServerPrefs.load(context).apiKey.isNotBlank())
            }
            HintPrefs.set(context,enabled,if(enabled)revision else ServerPrefs.revision(context))
            if(!enabled) {
                val notifications=context.getSystemService(NotificationManager::class.java)
                notifications.activeNotifications.filter {it.tag?.startsWith("shade-hint:")==true}
                    .forEach {notifications.cancel(it.tag,it.id)}
            }
        }
        if(enabled) {
            manager.enqueueUniquePeriodicWork(PERIODIC,ExistingPeriodicWorkPolicy.KEEP,
                PeriodicWorkRequestBuilder<LocalHintWorker>(15,TimeUnit.MINUTES)
                    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,15,TimeUnit.MINUTES).build())
            checkNow(context)
        }
    }
    fun checkNow(context:Context,resume:Boolean=false) {
        if(!HintPrefs.enabled(context))return
        if(resume)HintPrefs.resume(context)
        WorkManager.getInstance(context).enqueueUniqueWork(NOW,ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<LocalHintWorker>()
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,15,TimeUnit.MINUTES).build())
    }
    @SuppressLint("MissingPermission")
    internal fun show(context:Context,revision:String,feed:String,id:Long) {
        if(!HintPrefs.enabled(context,revision) || ServerPrefs.revision(context)!=revision || !permission(context))return
        val intent=Intent(context,MainActivity::class.java).setAction(OPEN_ACTION)
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val open=PendingIntent.getActivity(context,0,intent,PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification=NotificationCompat.Builder(context,CHANNEL)
            .setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle("Подсказка Shade")
            .setContentText("Вы дома. В Core есть событие доставки.")
            .setContentIntent(open).setAutoCancel(true).setOnlyAlertOnce(true).build()
        NotificationManagerCompat.from(context).notify("shade-hint:$revision:$feed:$id",0,notification)
    }
}

class LocalHintWorker(context:Context,params:WorkerParameters):CoroutineWorker(context,params) {
    override suspend fun doWork():Result=HintDelivery.mutex.withLock {
        val app=applicationContext
        val revision=ServerPrefs.revision(app)
        if(!HintPrefs.enabled(app,revision) || HintPrefs.error(app)!=null || !HintDelivery.permission(app))return@withLock Result.success()
        if(app.getSystemService(ConnectivityManager::class.java).allNetworks.isEmpty())return@withLock retryBounded()
        try {
            val saved=ServerPrefs.load(app)
            if(ServerPrefs.revision(app)!=revision || saved.apiKey.isBlank())return@withLock Result.success()
            val manager=app.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(HintDelivery.CHANNEL,"Подсказки Core",NotificationManager.IMPORTANCE_DEFAULT))
            if(manager.getNotificationChannel(HintDelivery.CHANNEL)?.importance==NotificationManager.IMPORTANCE_NONE)return@withLock Result.success()
            val cursor=HintPrefs.cursor(app)
            val response=ShadeApi.create(saved.baseUrl,saved.apiKey).hints(cursor.id)
            if(ServerPrefs.revision(app)!=revision || !HintPrefs.enabled(app,revision))return@withLock Result.success()
            val plan=planHints(response,cursor,Instant.now())
            for(item in plan.show) HintDelivery.show(app,revision,plan.next.feed!!,item.id)
            if(!HintPrefs.save(app,revision,plan.next))return@withLock retryBounded()
            Result.success()
        } catch(error:CancellationException){throw error
        } catch(error:HttpException){if(error.code() in listOf(401,403,404)){
            runCatching { HintPrefs.pause(app,revision,if(error.code()==404)"unsupported" else "access") }
                .fold(onSuccess={Result.success()},onFailure={retryBounded()})
        }else retryBounded()
        } catch(_:Exception){retryBounded()}
    }
    private fun retryBounded()=if(runAttemptCount<3)Result.retry() else Result.success()
}
