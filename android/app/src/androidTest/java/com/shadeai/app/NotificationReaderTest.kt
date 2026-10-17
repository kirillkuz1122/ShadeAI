package com.shadeai.app

import android.app.Notification
import android.os.Bundle
import android.text.SpannableString
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.shadeai.app.service.NotificationReader
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class NotificationReaderTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private fun notification(): Notification = Notification.Builder(context, "task11-test")
        .setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle("Заказ").setContentText("Готов").build()

    @Test fun plainExpandedAndInboxFormatsKeepTheMeaningfulText() {
        val plain = notification()
        assertEquals("Готов", NotificationReader.read(plain)!!.text)
        plain.extras.putCharSequence(Notification.EXTRA_BIG_TEXT, SpannableString("  Курьер в пути  "))
        plain.extras.putCharSequence(Notification.EXTRA_TITLE_BIG, "  Доставка  ")
        assertEquals("Курьер в пути", NotificationReader.read(plain)!!.text)
        assertEquals("Доставка", NotificationReader.read(plain)!!.title)
        plain.extras.remove(Notification.EXTRA_BIG_TEXT)
        plain.extras.putCharSequenceArray(Notification.EXTRA_TEXT_LINES, arrayOf("В пути", "", "Рядом"))
        assertEquals("В пути\nРядом", NotificationReader.read(plain)!!.text)
        assertFalse(NotificationReader.read(plain).toString().contains("Рядом"))
    }

    @Test fun missingFieldsAndTickerAreHandledWithoutNullText() {
        val n = notification(); n.extras = Bundle()
        n.tickerText = "Доставка готова"
        assertEquals("", NotificationReader.read(n)!!.title)
        assertEquals("Доставка готова", NotificationReader.read(n)!!.text)
        n.tickerText = null; n.extras.putCharSequence(Notification.EXTRA_TITLE, "Заказ готов")
        assertEquals("", NotificationReader.read(n)!!.text)
        n.extras.clear(); assertNull(NotificationReader.read(n))
    }

    @Test fun secretsInAnyVariantOrSubtextAreRejectedBeforeSelection() {
        val n = notification(); n.extras.putCharSequence(Notification.EXTRA_BIG_TEXT, "Доставка готова")
        n.extras.putCharSequence(Notification.EXTRA_TEXT, "Код 1234")
        assertNull(NotificationReader.read(n))
        n.extras.putCharSequence(Notification.EXTRA_TEXT, "Готов")
        n.tickerText = "Пароль — синтетика"; assertNull(NotificationReader.read(n))
        n.tickerText = null; n.extras.putCharSequence(Notification.EXTRA_SUB_TEXT, "OTP")
        assertNull(NotificationReader.read(n))
    }

    @Test fun serviceFlagsMessagesAndSystemRedactionAreSkipped() {
        for (flag in listOf(Notification.FLAG_ONGOING_EVENT, Notification.FLAG_FOREGROUND_SERVICE,
            Notification.FLAG_GROUP_SUMMARY, Notification.FLAG_LOCAL_ONLY)) {
            val n = notification(); n.flags = n.flags or flag; assertNull(NotificationReader.read(n))
        }
        val n = notification(); n.extras.putString(Notification.EXTRA_MESSAGES, "synthetic")
        assertNull(NotificationReader.read(n))
        n.extras.remove(Notification.EXTRA_MESSAGES)
        n.extras.putCharSequence(Notification.EXTRA_TEXT, "Скрыто системой")
        assertNull(NotificationReader.read(n, "Скрыто системой"))
    }

    @Test fun oversizedAndMalformedExtrasAreRejectedWithoutTruncation() {
        val n = notification(); n.extras.putCharSequence(Notification.EXTRA_BIG_TEXT, "Я".repeat(8193))
        assertNull(NotificationReader.read(n))
        n.extras.remove(Notification.EXTRA_BIG_TEXT)
        n.extras.putCharSequenceArray(Notification.EXTRA_TEXT_LINES, Array(101) { "строка" })
        assertNull(NotificationReader.read(n))
        n.extras.remove(Notification.EXTRA_TEXT_LINES)
        n.extras.putInt(Notification.EXTRA_TITLE, 123)
        assertNull(NotificationReader.read(n))
    }
}
