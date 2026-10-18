package com.shadeai.app

import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.shadeai.app.core.network.DeliveryFailure
import com.shadeai.app.core.network.toRequest
import com.shadeai.app.data.db.*
import com.shadeai.app.service.NotificationCapture
import com.shadeai.app.service.NotificationIdentity
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class NotificationQueueTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private var db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
    private var now = 1_800_000_000_000L
    private var revision = "first"
    private var sends = 0
    private var outcome: suspend (PendingNotificationEntity) -> DeliveryStatus = { DeliveryStatus.SENT }
    private fun capture() = NotificationCapture(db.pendingNotifications(), { setOf(PKG) }, {}, { true },
        { sends++; outcome(it) }, { now }, { revision })
    private suspend fun add(capture: NotificationCapture, index: Int = 0) =
        capture.record(PKG, "Заказ", "Синтетическая доставка", now, NotificationIdentity.hash(index.toString()))!!

    @After fun cleanup() { db.close(); context.deleteDatabase(NAME) }

    @Test fun batchesContinuePastOneHundredWithoutResendingAcknowledgedRows() = runBlocking {
        val capture = capture()
        repeat(105) { add(capture, it) }
        capture.sync()
        assertEquals(100, sends); assertEquals(0L, capture.nextDelay())
        capture.sync()
        assertEquals(105, sends); assertNull(capture.nextDelay())
        assertTrue(db.pendingNotifications().unsent().isEmpty())
    }

    @Test fun failureDelaysWholeQueueAndSurvivesReopenAndNewEvents() = runBlocking {
        db.close(); db = AppDatabase.create(context, NAME)
        var capture = capture()
        add(capture); add(capture, 1)
        outcome = { throw java.io.IOException("Синтетическая ошибка") }
        capture.sync(); assertEquals(1, sends); assertEquals(30_000L, capture.nextDelay())
        db.close(); db = AppDatabase.create(context, NAME); capture = capture()
        add(capture, 2); capture.sync(); assertEquals(1, sends)
        now += 30_000; capture.sync(); assertEquals(2, sends)
        assertEquals(60_000L, capture.nextDelay())
        now += 60_000; outcome = { DeliveryStatus.SENT }; capture.sync()
        assertEquals(5, sends); assertNull(capture.nextDelay())
    }

    @Test fun unauthorizedPausesAllRowsUntilSettingsRevisionChanges() = runBlocking {
        db.close(); db = AppDatabase.create(context, NAME)
        var capture = capture(); val first = add(capture); add(capture, 1)
        outcome = { throw DeliveryFailure("http_401", pause = true) }
        capture.sync(); assertEquals(1, sends); assertNull(capture.nextDelay())
        db.close(); db = AppDatabase.create(context, NAME); capture = capture()
        now += NotificationCapture.DAY; add(capture, 2); capture.sync()
        assertEquals(1, sends)
        assertEquals("http_401", db.pendingNotifications().byId(first)!!.lastError)
        revision = "corrected"; outcome = { DeliveryStatus.SENT }; capture.sync()
        assertEquals(4, sends); assertNull(capture.nextDelay())
    }

    @Test fun invalidRowIsTerminalButDoesNotBlockNextRow() = runBlocking {
        val capture = capture(); val bad = add(capture); val good = add(capture, 1)
        outcome = { if (it.id == bad) throw DeliveryFailure("http_422", permanent = true) else DeliveryStatus.SENT }
        capture.sync(); capture.sync()
        assertEquals(2, sends)
        val rejected = db.pendingNotifications().byId(bad)!!
        assertEquals(DeliveryStatus.REJECTED, rejected.status)
        assertEquals("http_422", rejected.lastError); assertNotNull(rejected.completedAt)
        assertEquals(DeliveryStatus.SENT, db.pendingNotifications().byId(good)!!.status)
    }

    @Test fun missingCredentialsWaitsForSettingsAndKeepsImmutablePayload() = runBlocking {
        val capture = capture(); val id = add(capture)
        val payload = db.pendingNotifications().byId(id)!!.toRequest()
        outcome = { DeliveryStatus.PENDING }
        capture.sync(); now += 60_000; capture.sync()
        assertEquals(1, sends); assertNull(capture.nextDelay())
        revision = "configured"; outcome = { DeliveryStatus.SENT }; capture.sync()
        val row = db.pendingNotifications().byId(id)!!
        assertEquals(payload, row.toRequest()); assertEquals(2, row.attempts); assertNull(row.lastError)
    }

    @Test fun receiptWriteFailurePropagatesAndLeavesIdentityForSafeRetry() = runBlocking {
        val capture = capture(); val id = add(capture)
        val before = db.pendingNotifications().byId(id)!!
        db.openHelper.writableDatabase.execSQL("CREATE TRIGGER fail_receipt BEFORE UPDATE ON pending_notifications BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        try { capture.deliver(id); fail("Ошибка Room должна передаваться worker для backoff") }
        catch (_: android.database.sqlite.SQLiteException) { }
        assertEquals(before, db.pendingNotifications().byId(id))
        db.openHelper.writableDatabase.execSQL("DROP TRIGGER fail_receipt")
        capture.sync()
        val after = db.pendingNotifications().byId(id)!!
        assertEquals(before.toRequest(), after.toRequest()); assertEquals(DeliveryStatus.SENT, after.status)
        assertEquals(2, sends)
    }

    @Test fun cappedBackoffDoesNotOverflow() {
        assertEquals(30_000L, NotificationCapture.backoff(1))
        assertEquals(60_000L, NotificationCapture.backoff(2))
        assertEquals(6 * 60 * 60_000L, NotificationCapture.backoff(Int.MAX_VALUE))
    }

    companion object { private const val PKG = "ru.ozon.app.android"; private const val NAME = "task12-queue-test.db" }
}
