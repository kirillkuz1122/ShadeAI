package com.shadeai.app.service

import android.content.Context
import android.net.ConnectivityManager
import androidx.work.*
import com.shadeai.app.ShadeApp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.TimeUnit

class NotificationDeliveryWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            val app = applicationContext as ShadeApp
            if (app.capture.nextDelay() == null) return@withContext Result.success()
            // Наличие локальной сети не требует INTERNET/VALIDATED; при полном офлайне HTTP не запускаем.
            if (app.getSystemService(ConnectivityManager::class.java).allNetworks.isEmpty()) {
                return@withContext Result.retry()
            }
            // Не более 100 запросов и 45 секунд; отменённая отправка остаётся неподтверждённой.
            withTimeoutOrNull(45_000) { app.capture.sync() }
            app.capture.nextDelay()?.let { app.delivery.continueAfter(it) }
            Result.success()
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
            Result.retry()
        }
    }
}

class NotificationRecoveryWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        (applicationContext as ShadeApp).delivery.wake()
        return Result.success()
    }
}

class NotificationDeliveryScheduler(context: Context) {
    private val manager = WorkManager.getInstance(context)

    fun start() {
        // Страхует запись перед гибелью процесса/гонку KEEP с завершающимся worker.
        manager.enqueueUniquePeriodicWork("notification-recovery", ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<NotificationRecoveryWorker>(15, TimeUnit.MINUTES).build())
        wake()
    }

    fun wake() {
        manager.enqueueUniqueWork(NAME, ExistingWorkPolicy.KEEP, request(0))
    }

    fun networkAvailable() = settingsChanged()

    fun settingsChanged() {
        manager.enqueueUniqueWork(NAME, ExistingWorkPolicy.REPLACE, request(0))
    }

    fun continueAfter(delay: Long) {
        manager.enqueueUniqueWork(NAME, ExistingWorkPolicy.APPEND_OR_REPLACE, request(delay))
    }

    private fun request(delay: Long) = OneTimeWorkRequestBuilder<NotificationDeliveryWorker>()
        // CONNECTED требует валидированный Интернет на части API. Core доступен и в изолированной LAN.
        .setInitialDelay(delay, TimeUnit.MILLISECONDS)
        .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
        .build()

    companion object { private const val NAME = "notification-delivery" }
}
