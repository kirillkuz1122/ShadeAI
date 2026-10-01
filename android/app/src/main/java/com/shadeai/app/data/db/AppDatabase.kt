package com.shadeai.app.data.db

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "pending_notifications")
data class PendingNotificationEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val packageName: String,
    val title: String,
    val text: String,
    val postTime: Long,
    val sent: Boolean = false,
)

@Dao
interface PendingNotificationDao {

    @Insert
    suspend fun insert(notification: PendingNotificationEntity): Long

    @Query("SELECT * FROM pending_notifications WHERE sent = 0 ORDER BY postTime ASC")
    suspend fun unsent(): List<PendingNotificationEntity>

    @Query("SELECT * FROM pending_notifications ORDER BY postTime DESC LIMIT 50")
    fun recent(): Flow<List<PendingNotificationEntity>>

    @Query("UPDATE pending_notifications SET sent = 1 WHERE id = :id")
    suspend fun markSent(id: Long)
}

@Database(entities = [PendingNotificationEntity::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {

    abstract fun pendingNotifications(): PendingNotificationDao

    companion object {
        fun create(context: Context): AppDatabase =
            Room.databaseBuilder(context, AppDatabase::class.java, "shade.db")
                .fallbackToDestructiveMigration()
                .build()
    }
}
