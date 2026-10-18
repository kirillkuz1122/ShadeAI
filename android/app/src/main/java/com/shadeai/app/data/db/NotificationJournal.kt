package com.shadeai.app.data.db

import androidx.room.InvalidationTracker
import androidx.room.withTransaction
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.map

const val JOURNAL_PAGE_SIZE = 50

enum class JournalFilter(val label: String, val statuses: Set<DeliveryStatus>) {
    ALL("Все", DeliveryStatus.entries.toSet()),
    QUEUED("В очереди", setOf(DeliveryStatus.PENDING, DeliveryStatus.FAILED)),
    SENT("Доставлено", setOf(DeliveryStatus.SENT)),
    SKIPPED("Пропущено", setOf(DeliveryStatus.SKIPPED)),
    REJECTED("Отклонено", setOf(DeliveryStatus.REJECTED)),
}

data class JournalCount(val status: DeliveryStatus, val count: Int)
data class JournalQuery(val filter: JournalFilter = JournalFilter.ALL, val beforeId: Long? = null)
data class JournalSnapshot(
    val rows: List<PendingNotificationEntity>,
    val counts: Map<DeliveryStatus, Int>,
    val hasMore: Boolean,
    val control: DeliveryControl?,
    val firstUnsent: PendingNotificationEntity?,
    val revision: String,
) {
    val total get() = counts.values.sum()
    val queued get() = (counts[DeliveryStatus.PENDING] ?: 0) + (counts[DeliveryStatus.FAILED] ?: 0)
    fun count(filter: JournalFilter) = filter.statuses.sumOf { counts[it] ?: 0 }
    override fun toString() = "JournalSnapshot(redacted)"
}

class NotificationJournal(private val database: AppDatabase, private val revision: () -> String = { "" }) {
    suspend fun read(query: JournalQuery): JournalSnapshot = database.withTransaction {
        val dao = database.pendingNotifications()
        val rows = dao.journalPage(query.filter.statuses, query.beforeId, JOURNAL_PAGE_SIZE + 1)
        JournalSnapshot(rows.take(JOURNAL_PAGE_SIZE), dao.journalCounts().associate { it.status to it.count },
            rows.size > JOURNAL_PAGE_SIZE, dao.control(), dao.unsent(1).firstOrNull(), revision())
    }

    fun observe(query: JournalQuery): Flow<JournalSnapshot> = callbackFlow {
        // Room 2.6: подписка до первого чтения, затем единый снимок строк/счётчиков/gate.
        val observer = object : InvalidationTracker.Observer("pending_notifications", "delivery_control") {
            override fun onInvalidated(tables: Set<String>) { trySend(Unit) }
        }
        database.invalidationTracker.addObserver(observer)
        trySend(Unit)
        awaitClose { database.invalidationTracker.removeObserver(observer) }
    }.conflate().map { read(query) }.flowOn(Dispatchers.IO)
}
