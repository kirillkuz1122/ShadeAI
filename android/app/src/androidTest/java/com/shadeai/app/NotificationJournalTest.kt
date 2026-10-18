package com.shadeai.app

import androidx.room.Room
import androidx.room.withTransaction
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.shadeai.app.data.db.*
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.collect
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class NotificationJournalTest {
    private val db = Room.inMemoryDatabaseBuilder(InstrumentationRegistry.getInstrumentation().targetContext, AppDatabase::class.java).build()
    private val dao = db.pendingNotifications()
    private val journal = NotificationJournal(db) { "current" }
    private val pkg = "ru.ozon.app.android"
    private suspend fun add(status: DeliveryStatus = DeliveryStatus.PENDING) = dao.insert(PendingNotificationEntity(
        packageName = pkg, title = "Синтетический заказ", text = "Синтетический текст", postTime = 123, status = status))
    @After fun cleanup() { db.close() }

    @Test fun emptyJournalHasNoQueueOrMorePages() = runBlocking {
        val page = journal.read(JournalQuery())
        assertTrue(page.rows.isEmpty()); assertEquals(0, page.total); assertEquals(0, page.queued); assertFalse(page.hasMore)
    }

    @Test fun cursorKeepsOlderPageStableWhenNewNotificationsArrive() = runBlocking {
        db.withTransaction { repeat(106) { add() } }
        val first = journal.read(JournalQuery())
        assertEquals((106L downTo 57L).toList(), first.rows.map { it.id }); assertTrue(first.hasMore)
        val query = JournalQuery(beforeId = first.rows.last().id)
        add()
        val second = journal.read(query)
        assertEquals((56L downTo 7L).toList(), second.rows.map { it.id }); assertTrue(second.hasMore)
        val third = journal.read(JournalQuery(beforeId = second.rows.last().id))
        assertEquals((6L downTo 1L).toList(), third.rows.map { it.id }); assertFalse(third.hasMore)
        assertEquals(107, third.total)
    }

    @Test fun filtersAndGlobalCountsIncludeAllRowsBeyondCurrentPage() = runBlocking {
        db.withTransaction {
            repeat(51) { add(DeliveryStatus.SENT) }; add(DeliveryStatus.PENDING); add(DeliveryStatus.FAILED)
            add(DeliveryStatus.SKIPPED); add(DeliveryStatus.REJECTED)
        }
        val sent = journal.read(JournalQuery(JournalFilter.SENT))
        assertEquals(50, sent.rows.size); assertTrue(sent.hasMore); assertEquals(51, sent.count(JournalFilter.SENT))
        assertEquals(55, sent.total); assertEquals(2, sent.queued)
        val pending = journal.read(JournalQuery(JournalFilter.QUEUED))
        assertEquals(setOf(DeliveryStatus.PENDING, DeliveryStatus.FAILED), pending.rows.map { it.status }.toSet())
        assertEquals(1, journal.read(JournalQuery(JournalFilter.REJECTED)).rows.size)
    }

    @Test fun observerSeesUpdatesAndAtomicGateEvenWhenRowCountIsUnchanged() = runBlocking {
        val updates = Channel<JournalSnapshot>(Channel.UNLIMITED)
        val job = launch { journal.observe(JournalQuery()).collect { updates.send(it) } }
        try {
            assertEquals(0, withTimeout(5000) { updates.receive() }.total)
            val id = add()
            withTimeout(5000) { while (updates.receive().total != 1) { } }
            dao.finish(id, DeliveryStatus.FAILED, null, "http_401", DeliveryControl(revision = "current", blocked = true))
            val changed = withTimeout(5000) {
                var value = updates.receive()
                while (value.rows.single().status != DeliveryStatus.FAILED) value = updates.receive()
                value
            }
            assertEquals("http_401", changed.rows.single().lastError); assertTrue(changed.control!!.blocked)
            assertEquals(1, changed.queued); assertEquals("current", changed.revision)
            dao.clear()
            withTimeout(5000) { while (updates.receive().rows.isNotEmpty()) { } }
        } finally { job.cancelAndJoin(); updates.close() }
    }

    @Test fun deletingViewedRowsDoesNotReturnStalePageContents() = runBlocking {
        repeat(51) { add() }
        val first = journal.read(JournalQuery())
        val query = JournalQuery(beforeId = first.rows.last().id)
        assertEquals(1, journal.read(query).rows.size)
        dao.clear()
        assertTrue(journal.read(query).rows.isEmpty())
        assertEquals(0, journal.read(query).total)
    }
}
