package com.shadeai.app

import android.database.sqlite.SQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.shadeai.app.data.db.AppDatabase
import com.shadeai.app.data.db.DeliveryStatus
import com.shadeai.app.data.db.PendingNotificationEntity
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class BufferMigrationTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private var upgraded: AppDatabase? = null

    @Before fun reset() { context.deleteDatabase(NAME) }
    @After fun cleanup() { upgraded?.close(); context.deleteDatabase(NAME) }

    private fun legacy(): SQLiteDatabase {
        val file = context.getDatabasePath(NAME)
        file.parentFile!!.mkdirs()
        val db = SQLiteDatabase.openOrCreateDatabase(file, null)
        val schema = instrumentation.context.assets.open("com.shadeai.app.data.db.AppDatabase/1.json")
            .bufferedReader().use { JSONObject(it.readText()).getJSONObject("database") }
        val entity = schema.getJSONArray("entities").getJSONObject(0)
        db.execSQL(entity.getString("createSql").replace("\${TABLE_NAME}", entity.getString("tableName")))
        val setup = schema.getJSONArray("setupQueries")
        for (i in 0 until setup.length()) db.execSQL(setup.getString(i))
        db.version = 1
        return db
    }

    private fun open(): AppDatabase = AppDatabase.create(context, NAME).also { upgraded = it }

    private fun SQLiteDatabase.add(id: Int, sent: Int) = execSQL(
        "INSERT INTO pending_notifications VALUES (?, 'ru.ozon.app.android', 'Заказ', 'Синтетический текст', 12345, ?)",
        arrayOf(id, sent))

    @Test fun migrationPreservesPayloadStatusAndAutoincrementAcrossReopen() = runBlocking {
        legacy().use { old -> old.add(1, 0); old.add(2, 1); old.add(100, 0); old.execSQL("DELETE FROM pending_notifications WHERE id = 100") }
        var db = open()
        val pending = db.pendingNotifications().byId(1)!!
        val sent = db.pendingNotifications().byId(2)!!
        assertEquals("Синтетический текст", pending.text)
        assertEquals(12345L, pending.postTime)
        assertEquals(DeliveryStatus.PENDING, pending.status); assertEquals(DeliveryStatus.SENT, sent.status)
        assertNull(pending.eventId); assertNull(sent.eventId)
        assertNotNull(sent.completedAt)
        val id = db.pendingNotifications().insert(PendingNotificationEntity(packageName = "ru.ozon.app.android",
            title = "Новый заказ", text = "Готов", postTime = 12346))
        assertEquals(101L, id)
        val uuid = db.pendingNotifications().byId(id)!!.eventId
        db.close(); db = open()
        assertEquals(uuid, db.pendingNotifications().byId(id)!!.eventId)
        assertEquals(3, db.pendingNotifications().count())
    }

    @Test fun emptyLegacyTableStillPreservesItsDeletedSequence() = runBlocking {
        legacy().use { it.add(77, 0); it.execSQL("DELETE FROM pending_notifications") }
        val id = open().pendingNotifications().insert(PendingNotificationEntity(
            packageName = "ru.ozon.app.android", title = "Заказ", text = "Готов", postTime = 1))
        assertEquals(78L, id)
    }

    @Test fun failedMigrationRollsBackWithoutDestroyingLegacyAndCanRecover() = runBlocking {
        legacy().use { it.add(5, 0); it.execSQL("CREATE TABLE pending_notifications_v2 (conflict TEXT)") }
        try { open().pendingNotifications().count(); fail("Конфликт должен прервать миграцию") }
        catch (_: RuntimeException) { }
        upgraded?.close()
        SQLiteDatabase.openDatabase(context.getDatabasePath(NAME).path, null, SQLiteDatabase.OPEN_READWRITE).use { raw ->
            assertEquals(1, raw.version)
            raw.rawQuery("SELECT title, sent FROM pending_notifications WHERE id = 5", null).use {
                assertTrue(it.moveToFirst()); assertEquals("Заказ", it.getString(0)); assertEquals(0, it.getInt(1))
            }
            raw.execSQL("DROP TABLE pending_notifications_v2")
        }
        assertEquals(1, open().pendingNotifications().count())
    }

    companion object { private const val NAME = "task11-migration-test.db" }
}
