package com.shadeai.app

import androidx.room.Room
import androidx.room.withTransaction
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.shadeai.app.core.network.NotificationIngest
import com.shadeai.app.core.network.toRequest
import com.shadeai.app.data.db.*
import com.shadeai.app.service.NotificationCapture
import com.shadeai.app.service.NotificationIdentity
import kotlinx.coroutines.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.IOException
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class NotificationBufferTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val pkg = "ru.ozon.app.android"
    private val key = NotificationIdentity.hash("synthetic-notification")
    private var now = 1_800_000_000_000L
    private var selected = setOf(pkg)
    private lateinit var db: AppDatabase
    private lateinit var capture: NotificationCapture
    private var transport: suspend (PendingNotificationEntity) -> DeliveryStatus = { DeliveryStatus.PENDING }

    @Before fun setup() {
        context.deleteDatabase(TEST_DB)
        db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
        capture = controller()
    }
    private fun controller() = NotificationCapture(db.pendingNotifications(), { selected },
        { selected = it }, { true }, { transport(it) }, { now })
    private suspend fun record(text: String = "Готов", sourceKey: String = key, time: Long = now) =
        capture.record(pkg, "Заказ", text, time, sourceKey)
    @After fun cleanup() { db.close(); context.deleteDatabase(TEST_DB) }

    @Test fun concurrentDuplicatesKeepOneImmutableVersion() = runBlocking {
        val ids = (1..20).map { async(Dispatchers.Default) { record() } }.awaitAll().filterNotNull()
        assertEquals(1, ids.size)
        val row = db.pendingNotifications().byId(ids.single())!!
        UUID.fromString(row.eventId)
        assertNull(record(time = now + 1000))
        assertEquals(row, db.pendingNotifications().byId(row.id))
    }

    @Test fun changesAreNewVersionsAndRemovalStartsANewLifecycle() = runBlocking {
        val first = record()!!
        val second = record("Курьер в пути")!!
        assertNull(record("Курьер в пути", time = now + 1000))
        val original = db.pendingNotifications().byId(first)!!
        val changed = db.pendingNotifications().byId(second)!!
        assertEquals("Готов", original.text)
        assertNotEquals(original.eventId, changed.eventId)
        capture.removed(key)
        val reposted = record("Курьер в пути")!!
        assertNotEquals(changed.eventId, db.pendingNotifications().byId(reposted)!!.eventId)
        assertNotNull(record(sourceKey = NotificationIdentity.hash("another-notification")))
        assertEquals(4, db.pendingNotifications().count())
    }

    @Test fun pendingAndDedupeHeadSurviveDatabaseReopen() = runBlocking {
        db.close(); db = AppDatabase.create(context, TEST_DB); capture = controller()
        val id = record()!!
        val original = db.pendingNotifications().byId(id)!!
        db.close(); db = AppDatabase.create(context, TEST_DB); capture = controller()
        assertEquals(original, db.pendingNotifications().byId(id))
        assertEquals(DeliveryStatus.PENDING, original.status)
        assertNull(record(time = now + 1000))
        assertEquals(1, db.pendingNotifications().count())
    }

    @Test fun lostResponseRetriesTheExactPersistedPayloadAndStopsAfterAck() = runBlocking {
        val requests = mutableListOf<NotificationIngest>()
        transport = { row -> requests += row.toRequest(); throw IOException("synthetic failure") }
        val id = record()!!
        capture.deliver(id)
        assertEquals(DeliveryStatus.FAILED, db.pendingNotifications().byId(id)!!.status)
        transport = { row -> requests += row.toRequest(); DeliveryStatus.SENT }
        capture.sync(); capture.deliver(id); capture.sync()
        assertEquals(2, requests.size)
        assertEquals(requests[0], requests[1])
        assertEquals(DeliveryStatus.SENT, db.pendingNotifications().byId(id)!!.status)
    }

    @Test fun networkWaitDoesNotBlockDurableCapture() = runBlocking {
        val started = CompletableDeferred<Unit>(); val finish = CompletableDeferred<Unit>()
        transport = { started.complete(Unit); finish.await(); DeliveryStatus.SENT }
        val id = record()!!
        val sending = launch { capture.deliver(id) }
        started.await()
        try {
            withTimeout(5000) { assertNotNull(record("Новая версия")) }
            assertEquals(2, db.pendingNotifications().count())
        } finally { finish.complete(Unit); sending.join() }
    }

    @Test fun cancellationLeavesPendingIdentityForTheNextSession() = runBlocking {
        val started = CompletableDeferred<Unit>()
        transport = { started.complete(Unit); awaitCancellation() }
        val id = record()!!
        val original = db.pendingNotifications().byId(id)!!
        val sending = launch { capture.deliver(id) }
        started.await(); sending.cancelAndJoin()
        assertEquals(original, db.pendingNotifications().byId(id))
        transport = { DeliveryStatus.SENT }; capture = controller(); capture.sync()
        assertEquals(original.eventId, db.pendingNotifications().byId(id)!!.eventId)
        assertEquals(DeliveryStatus.SENT, db.pendingNotifications().byId(id)!!.status)
    }

    @Test fun terminalCleanupKeepsDedupeAndExpiredPendingDoesNotSend() = runBlocking {
        transport = { DeliveryStatus.SKIPPED }
        val id = record()!!; capture.deliver(id)
        assertEquals(DeliveryStatus.SKIPPED, db.pendingNotifications().byId(id)!!.status)
        assertTrue(db.pendingNotifications().unsent().isEmpty())
        now += NotificationCapture.DAY + 1; capture.refresh()
        assertEquals(0, db.pendingNotifications().count())
        assertNull(record())
        now += 7 * NotificationCapture.DAY + 1; capture.refresh()
        val pending = record()!!
        now += 8 * NotificationCapture.DAY
        var sends = 0; transport = { sends++; DeliveryStatus.SENT }
        capture.deliver(pending)
        assertEquals(0, sends); assertEquals(0, db.pendingNotifications().count())
    }

    @Test fun capacityIsBoundedAndExpiredRowsFreeSpaceWithoutIdReuse() = runBlocking {
        db.withTransaction {
            repeat(1000) { db.pendingNotifications().insert(PendingNotificationEntity(
                packageName = pkg, title = "Заказ", text = "Готов", postTime = now, createdAt = now)) }
        }
        assertNull(record()); assertEquals(1000, db.pendingNotifications().count())
        now += 8 * NotificationCapture.DAY; capture.refresh()
        assertTrue(record()!! > 1000)
    }

    @Test fun staleDeliverySnapshotCannotResendDeletedRowsAfterReenable() = runBlocking {
        val id = record()!!
        capture.choose(emptySet()); capture.choose(setOf(pkg))
        var sends = 0; transport = { sends++; DeliveryStatus.SENT }
        capture.deliver(id)
        assertEquals(0, sends); assertNull(db.pendingNotifications().head(key))
    }

    @Test fun reconnectMarksMissingNotificationsRemovedWithoutImportingHistory() = runBlocking {
        val first = record()!!
        capture.connected(setOf(key))
        assertNull(record())
        capture.connected(emptySet())
        val second = record()!!
        assertNotEquals(db.pendingNotifications().byId(first)!!.eventId,
            db.pendingNotifications().byId(second)!!.eventId)
    }

    @Test fun dedupeMetadataIsBoundedAndInactiveEntriesArePrunedFirst() = runBlocking {
        val old = NotificationIdentity.hash("old-inactive")
        db.withTransaction {
            db.pendingNotifications().putHead(NotificationHead(old, pkg, "hash", UUID.randomUUID().toString(), false, now))
            repeat(1999) { db.pendingNotifications().putHead(NotificationHead(
                NotificationIdentity.hash(it.toString()), pkg, "hash", UUID.randomUUID().toString(), true, now)) }
        }
        assertNotNull(record())
        assertNull(db.pendingNotifications().head(old))
        db.openHelper.readableDatabase.query("SELECT count(*) FROM notification_heads").use {
            assertTrue(it.moveToFirst()); assertEquals(2000, it.getInt(0))
        }
    }

    companion object { private const val TEST_DB = "task11-buffer-test.db" }
}
