package com.shadeai.app.service

import com.shadeai.app.data.db.DeliveryStatus
import com.shadeai.app.data.db.PendingNotificationDao
import com.shadeai.app.data.db.PendingNotificationEntity
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class NotificationCapture(
    private val dao: PendingNotificationDao,
    private val selected: () -> Set<String>,
    private val save: (Set<String>) -> Unit,
    private val access: () -> Boolean,
    private val send: suspend (PendingNotificationEntity) -> DeliveryStatus,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private val stateMutex = Mutex()
    private val deliveryMutex = Mutex()

    // Общий порядок блокировок: delivery → state; запись новых событий не ждёт сеть.
    suspend fun choose(sources: Set<String>) = deliveryMutex.withLock {
        stateMutex.withLock { save(sources); purge() }
    }

    suspend fun refresh() = stateMutex.withLock { purge() }

    private suspend fun expire() {
        val now = clock()
        dao.expire(now - 7 * DAY, now - DAY)
        dao.expireHeads(now - 7 * DAY)
    }

    private suspend fun purge() {
        expire()
        val sources = if (access()) selected() else emptySet()
        if (sources.isEmpty()) { dao.clear(); dao.clearHeads() }
        else { dao.deleteOtherSources(sources); dao.deleteOtherHeads(sources) }
        var after = 0L
        while (true) {
            val rows = dao.page(after)
            if (rows.isEmpty()) break
            for (item in rows) {
                if (!NotificationPolicy.allows(item.packageName, item.title, item.text, sources)) dao.delete(item.id)
            }
            after = rows.last().id
        }
    }

    suspend fun record(pkg: String, title: String, text: String, postTime: Long,
                       sourceKey: String = NotificationIdentity.hash(pkg, postTime.toString())): Long? = quietly {
        stateMutex.withLock {
            if (!access() || !NotificationPolicy.allows(pkg, title, text, selected())) return@withLock null
            require(sourceKey.matches(Regex("[a-f0-9]{64}")))
            val normalizedTitle = title.trim()
            val normalizedText = text.replace("\r\n", "\n").trim()
            expire()
            dao.record(PendingNotificationEntity(packageName = pkg, title = normalizedTitle,
                text = normalizedText, postTime = postTime, sourceKey = sourceKey,
                contentHash = NotificationIdentity.hash(pkg, normalizedTitle, normalizedText), createdAt = clock()))
        }
    }

    suspend fun removed(key: String) { quietly { stateMutex.withLock { dao.removed(key) } } }

    suspend fun connected(activeKeys: Set<String>?) {
        quietly { stateMutex.withLock { purge(); if (activeKeys != null) dao.reconcile(activeKeys) } }
    }

    suspend fun sync() {
        val pending = quietly { stateMutex.withLock { purge(); dao.unsent() } }.orEmpty()
        for (item in pending) deliver(item.id)
    }

    suspend fun deliver(id: Long) {
        quietly {
            deliveryMutex.withLock delivery@ {
                val item = stateMutex.withLock row@ {
                    val row = dao.byId(id) ?: return@row null
                    if (row.status == DeliveryStatus.SENT || row.status == DeliveryStatus.SKIPPED) return@row null
                    if (!access() || !NotificationPolicy.allows(row.packageName, row.title, row.text, selected()) ||
                        row.createdAt < clock() - 7 * DAY) {
                        dao.delete(id)
                        return@row null
                    }
                    row
                } ?: return@delivery
                val result = try { send(item) }
                    catch (error: CancellationException) { throw error }
                    catch (_: Exception) { DeliveryStatus.FAILED }
                stateMutex.withLock {
                    dao.markResult(id, result, if (result == DeliveryStatus.SENT || result == DeliveryStatus.SKIPPED) clock() else null)
                }
            }
        }
    }

    private suspend fun <T> quietly(action: suspend () -> T): T? = try { action() }
        catch (error: CancellationException) { throw error }
        catch (_: Exception) { null }

    companion object { const val DAY = 86_400_000L }
}
