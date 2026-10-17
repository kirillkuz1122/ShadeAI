package com.shadeai.app.data.db

import android.content.Context
import androidx.room.*
import kotlinx.coroutines.flow.Flow
import java.util.UUID

enum class DeliveryStatus { PENDING, SENT, SKIPPED, FAILED }

class BufferConverters {
    @TypeConverter fun encode(value: DeliveryStatus) = value.name
    @TypeConverter fun decode(value: String) = DeliveryStatus.valueOf(value)
}

@Entity(tableName = "pending_notifications", indices = [Index(value = ["eventId"], unique = true), Index(value = ["status", "createdAt"])])
data class PendingNotificationEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val packageName: String,
    val title: String,
    val text: String,
    val postTime: Long,
    val eventId: String? = UUID.randomUUID().toString(),
    val sourceKey: String? = null,
    val contentHash: String = "",
    val status: DeliveryStatus = DeliveryStatus.PENDING,
    val createdAt: Long = System.currentTimeMillis(),
    val completedAt: Long? = null,
) {
    override fun toString() = "PendingNotification(id=$id, status=$status)"
}

@Entity(tableName = "notification_heads", indices = [Index("updatedAt")])
data class NotificationHead(
    @PrimaryKey val sourceKey: String,
    val packageName: String,
    val contentHash: String,
    val eventId: String,
    val active: Boolean,
    val updatedAt: Long,
)

@Dao
interface PendingNotificationDao {
    @Insert suspend fun insert(notification: PendingNotificationEntity): Long
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun putHead(head: NotificationHead)
    @Query("SELECT * FROM notification_heads WHERE sourceKey = :key") suspend fun head(key: String): NotificationHead?
    @Query("SELECT * FROM pending_notifications WHERE id = :id") suspend fun byId(id: Long): PendingNotificationEntity?
    @Query("SELECT count(*) FROM pending_notifications") suspend fun count(): Int
    @Query("SELECT * FROM pending_notifications WHERE status IN ('PENDING', 'FAILED') ORDER BY id LIMIT :limit")
    suspend fun unsent(limit: Int = 100): List<PendingNotificationEntity>
    @Query("SELECT * FROM pending_notifications ORDER BY id DESC LIMIT 50") fun recent(): Flow<List<PendingNotificationEntity>>
    @Query("SELECT * FROM pending_notifications WHERE id > :after ORDER BY id LIMIT 100")
    suspend fun page(after: Long): List<PendingNotificationEntity>
    @Query("UPDATE pending_notifications SET status = :status, completedAt = :completedAt WHERE id = :id")
    suspend fun markResult(id: Long, status: DeliveryStatus, completedAt: Long?)
    @Query("DELETE FROM pending_notifications WHERE packageName NOT IN (:selected)") suspend fun deleteOtherSources(selected: Set<String>)
    @Query("DELETE FROM notification_heads WHERE packageName NOT IN (:selected)") suspend fun deleteOtherHeads(selected: Set<String>)
    @Query("DELETE FROM pending_notifications") suspend fun clear()
    @Query("DELETE FROM notification_heads") suspend fun clearHeads()
    @Query("DELETE FROM pending_notifications WHERE id = :id") suspend fun delete(id: Long)
    @Query("UPDATE notification_heads SET active = 0 WHERE sourceKey = :key") suspend fun removed(key: String)
    @Query("UPDATE notification_heads SET active = 0 WHERE sourceKey NOT IN (:activeKeys)") suspend fun reconcile(activeKeys: Set<String>)
    @Query("DELETE FROM pending_notifications WHERE createdAt < :oldest OR (status IN ('SENT','SKIPPED') AND completedAt < :completedBefore)")
    suspend fun expire(oldest: Long, completedBefore: Long)
    @Query("DELETE FROM notification_heads WHERE updatedAt < :oldest") suspend fun expireHeads(oldest: Long)
    @Query("DELETE FROM notification_heads WHERE sourceKey IN (SELECT sourceKey FROM notification_heads ORDER BY active, updatedAt, sourceKey LIMIT max(0, (SELECT count(*) FROM notification_heads) - 2000))")
    suspend fun trimHeads()

    @Transaction
    suspend fun record(item: PendingNotificationEntity): Long? {
        val key = requireNotNull(item.sourceKey)
        val head = head(key)
        if (head?.active == true && head.contentHash == item.contentHash) {
            putHead(head.copy(updatedAt = item.createdAt))
            return null
        }
        if (count() >= 1000) return null
        val id = insert(item)
        putHead(NotificationHead(key, item.packageName, item.contentHash, requireNotNull(item.eventId), true, item.createdAt))
        trimHeads()
        return id
    }
}

@Database(entities = [PendingNotificationEntity::class, NotificationHead::class], version = 2, exportSchema = true)
@TypeConverters(BufferConverters::class)
abstract class AppDatabase : RoomDatabase() {
    abstract fun pendingNotifications(): PendingNotificationDao
    companion object {
        fun create(context: Context, name: String = "shade.db"): AppDatabase =
            Room.databaseBuilder(context, AppDatabase::class.java, name)
                .addMigrations(BufferMigrations.FROM_1_TO_2).build()
    }
}
