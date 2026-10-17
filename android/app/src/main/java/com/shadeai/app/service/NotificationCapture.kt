package com.shadeai.app.service

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
    private val send: suspend (PendingNotificationEntity) -> Boolean,
) {
    private val mutex = Mutex()

    // Сохранение выбора и отправка упорядочены: после завершения отключения новых запросов нет.
    suspend fun choose(sources: Set<String>) = mutex.withLock {
        save(sources)
        purge()
    }

    suspend fun refresh() = mutex.withLock { purge() }

    private suspend fun purge() {
        val sources = if (access()) selected() else emptySet()
        if (sources.isEmpty()) dao.clear() else dao.deleteOtherSources(sources)
    }

    suspend fun receive(pkg: String, title: String, text: String, postTime: Long) = safely {
        mutex.withLock {
            if (!access() || !NotificationPolicy.allows(pkg, title, text, selected())) return@withLock
            val item = PendingNotificationEntity(packageName = pkg, title = title, text = text, postTime = postTime)
            val id = dao.insert(item)
            deliver(item.copy(id = id))
        }
    }

    suspend fun sync() = safely {
        val pending = mutex.withLock {
            purge()
            dao.unsent()
        }
        for (item in pending) safely { mutex.withLock { deliver(item) } }
    }

    private suspend fun deliver(item: PendingNotificationEntity) {
        if (!access() || !NotificationPolicy.allows(item.packageName, item.title, item.text, selected())) {
            dao.delete(item.id)
            return
        }
        if (send(item)) dao.markSent(item.id)
    }

    private suspend fun safely(action: suspend () -> Unit) {
        try { action() }
        catch (error: CancellationException) { throw error }
        catch (_: Exception) { /* Содержимое уведомления и ошибки транспорта не попадают в логи. */ }
    }
}
