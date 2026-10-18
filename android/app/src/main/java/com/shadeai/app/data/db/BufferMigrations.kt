package com.shadeai.app.data.db

import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

object BufferMigrations {
    val FROM_2_TO_3 = object : Migration(2, 3) {
        override fun migrate(db: SupportSQLiteDatabase) {
            db.execSQL("ALTER TABLE pending_notifications ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
            db.execSQL("ALTER TABLE pending_notifications ADD COLUMN lastError TEXT")
            db.execSQL("""CREATE TABLE delivery_control (
                id INTEGER NOT NULL PRIMARY KEY, revision TEXT NOT NULL, failures INTEGER NOT NULL,
                nextAttemptAt INTEGER NOT NULL, blocked INTEGER NOT NULL)""")
        }
    }

    val FROM_1_TO_2 = object : Migration(1, 2) {
        override fun migrate(db: SupportSQLiteDatabase) {
            val previousSequence = db.query("SELECT seq FROM sqlite_sequence WHERE name = 'pending_notifications'").use {
                if (it.moveToFirst()) it.getLong(0) else 0L
            }
            db.execSQL("""CREATE TABLE pending_notifications_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                packageName TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, postTime INTEGER NOT NULL,
                eventId TEXT, sourceKey TEXT, contentHash TEXT NOT NULL, status TEXT NOT NULL,
                createdAt INTEGER NOT NULL, completedAt INTEGER)""")
            val now = System.currentTimeMillis()
            // Старые отправки не имели UUID: NULL сохраняет серверную дедупликацию по отпечатку.
            db.execSQL("""INSERT INTO pending_notifications_v2
                SELECT id, packageName, title, text, postTime, NULL, NULL, '',
                CASE WHEN sent = 1 THEN 'SENT' ELSE 'PENDING' END, ?,
                CASE WHEN sent = 1 THEN ? ELSE NULL END FROM pending_notifications""", arrayOf(now, now))
            db.execSQL("DROP TABLE pending_notifications")
            db.execSQL("ALTER TABLE pending_notifications_v2 RENAME TO pending_notifications")
            db.execSQL("INSERT INTO sqlite_sequence(name, seq) SELECT 'pending_notifications', ? WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = 'pending_notifications')", arrayOf(previousSequence))
            db.execSQL("UPDATE sqlite_sequence SET seq = max(seq, ?) WHERE name = 'pending_notifications'", arrayOf(previousSequence))
            db.execSQL("CREATE UNIQUE INDEX index_pending_notifications_eventId ON pending_notifications(eventId)")
            db.execSQL("CREATE INDEX index_pending_notifications_status_createdAt ON pending_notifications(status, createdAt)")
            db.execSQL("""CREATE TABLE notification_heads (
                sourceKey TEXT NOT NULL PRIMARY KEY, packageName TEXT NOT NULL, contentHash TEXT NOT NULL,
                eventId TEXT NOT NULL, active INTEGER NOT NULL, updatedAt INTEGER NOT NULL)""")
            db.execSQL("CREATE INDEX index_notification_heads_updatedAt ON notification_heads(updatedAt)")
        }
    }
}
