package com.shadeai.app

import android.content.Context
import android.content.ContextWrapper
import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.shadeai.app.core.config.NotificationSources
import com.shadeai.app.data.db.DeliveryStatus
import com.shadeai.app.data.db.AppDatabase
import com.shadeai.app.data.db.PendingNotificationEntity
import com.shadeai.app.service.NotificationCapture
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class NotificationCaptureTest {
    private val target = InstrumentationRegistry.getInstrumentation().targetContext
    private val context = object : ContextWrapper(target) {
        override fun getSharedPreferences(name: String, mode: Int) = super.getSharedPreferences("task10_test_$name", mode)
    }
    private lateinit var db: AppDatabase
    private val pkg = "ru.ozon.app.android"
    private var access = true
    private var sent = 0
    private lateinit var capture: NotificationCapture

    @Before fun setup() {
        context.getSharedPreferences("notification_sources", Context.MODE_PRIVATE).edit().clear().commit()
        db = Room.inMemoryDatabaseBuilder(target, AppDatabase::class.java).build()
        capture = controller { sent++; DeliveryStatus.SENT }
    }

    private fun controller(send: suspend (PendingNotificationEntity) -> DeliveryStatus) = NotificationCapture(
        db.pendingNotifications(), { NotificationSources.load(context) },
        { NotificationSources.save(context, it) }, { access }, send)

    private suspend fun receive(pkg: String, title: String, text: String, time: Long) {
        capture.record(pkg, title, text, time)?.let { capture.deliver(it) }
    }

    @After fun cleanup() {
        db.close()
        context.getSharedPreferences("notification_sources", Context.MODE_PRIVATE).edit().clear().commit()
    }

    @Test fun selectionPersistsAndUnknownSourcesFailClosed() {
        assertEquals(emptySet<String>(), NotificationSources.load(context))
        NotificationSources.save(context, setOf(pkg))
        assertEquals(setOf(pkg), NotificationSources.load(context))
        context.getSharedPreferences("notification_sources", Context.MODE_PRIVATE).edit()
            .putStringSet("selected", setOf(pkg, "org.telegram.messenger")).commit()
        assertEquals(setOf(pkg), NotificationSources.load(context))
        try { NotificationSources.save(context, setOf("org.telegram.messenger")); fail("Источник запрещён") }
        catch (_: IllegalArgumentException) { }
    }

    @Test fun disabledPrivateAndSensitiveNeverReachRoomOrTransport() = runBlocking {
        receive(pkg, "Заказ", "Готов", 1)
        capture.choose(setOf(pkg))
        receive(pkg, "Код 1234", "Доставка", 2)
        receive("org.telegram.messenger", "Пример", "Синтетика", 3)
        receive("com.wildberries.ru", "Заказ", "Готов", 4)
        assertEquals(0, sent)
        assertTrue(db.pendingNotifications().recent().first().isEmpty())
        receive(pkg, "Заказ", "Готов", 5)
        assertEquals(1, sent)
        assertEquals(1, db.pendingNotifications().recent().first().size)
    }

    @Test fun disablingPurgesOfflineBufferAndPreventsReconnectSend() = runBlocking {
        capture = controller { DeliveryStatus.PENDING }
        capture.choose(setOf(pkg))
        receive(pkg, "Заказ", "Готов", 1)
        assertEquals(1, db.pendingNotifications().unsent().size)
        capture.choose(emptySet())
        capture = controller { sent++; DeliveryStatus.SENT }
        capture.sync()
        receive(pkg, "Заказ", "Готов", 2)
        assertTrue(db.pendingNotifications().recent().first().isEmpty())
        assertEquals(0, sent)
    }

    @Test fun revokedAccessPurgesAndBlocksNewCapture() = runBlocking {
        capture = controller { DeliveryStatus.PENDING }
        capture.choose(setOf(pkg))
        receive(pkg, "Заказ", "Готов", 1)
        access = false
        capture.sync()
        receive(pkg, "Заказ", "Готов", 2)
        assertTrue(db.pendingNotifications().recent().first().isEmpty())
    }

    @Test fun pendingSensitiveLegacyRecordIsDeletedWithoutSending() = runBlocking {
        capture.choose(setOf(pkg))
        db.pendingNotifications().insert(PendingNotificationEntity(packageName = pkg,
            title = "пароль", text = "Пример", postTime = 1))
        capture.sync()
        assertEquals(0, sent)
        assertTrue(db.pendingNotifications().recent().first().isEmpty())
    }

    @Test fun confirmedDisableWaitsForInFlightRequestAndSerializesFutureCapture() = runBlocking {
        val started = CompletableDeferred<Unit>()
        val finish = CompletableDeferred<Unit>()
        capture = controller { started.complete(Unit); finish.await(); sent++; DeliveryStatus.SENT }
        capture.choose(setOf(pkg))
        val receiving = async { receive(pkg, "Заказ", "Готов", 1) }
        started.await()
        val disabling = async { capture.choose(emptySet()) }
        finish.complete(Unit)
        receiving.await(); disabling.await()
        receive(pkg, "Заказ", "Готов", 2)
        capture.sync()
        assertEquals(1, sent)
        assertTrue(db.pendingNotifications().recent().first().isEmpty())
    }
}
