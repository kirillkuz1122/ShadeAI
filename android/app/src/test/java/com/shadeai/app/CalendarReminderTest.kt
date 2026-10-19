package com.shadeai.app

import com.shadeai.app.core.network.*
import com.shadeai.app.reminders.*
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class CalendarReminderTest {
    private val now=Instant.parse("2026-10-19T04:00:00Z")
    private val item=CoreReminder("rmd_"+"a".repeat(32),"cal_"+"b".repeat(32),1,now.toString(),now.plusSeconds(300).toString(),true)
    private val page=CoreReminderPage(1,"c".repeat(64),"d".repeat(64),true,true,false,now.toString(),"Asia/Yekaterinburg",10,300,reminders=listOf(item))
    private fun rejects(action:()->Unit){try{action();fail("Должно быть отклонено")}catch(_:IllegalArgumentException){}}
    @Test fun dueAndExpiry(){
        assertEquals(listOf(item),validateReminders(page,now))
        assertTrue(reminderMayShow(page,item,now))
        assertFalse(reminderMayShow(page,item,now.plusSeconds(300)))
        assertFalse(reminderMayShow(page,item,now.minusSeconds(1)))
    }
    @Test fun noStaleDisabledOverflow(){
        assertFalse(reminderMayShow(page.copy(stale=true),item,now))
        assertFalse(reminderMayShow(page.copy(enabled=false),item,now))
        assertFalse(reminderMayShow(page.copy(configured=false),item,now))
        assertFalse(reminderMayShow(page.copy(overflow=true),item,now))
    }
    @Test fun unknownPolicyClockAndBounds(){
        rejects{validateReminders(page.copy(version=2),now)}
        rejects{validateReminders(page.copy(sourceId="bad"),now)}
        rejects{validateReminders(page,now.plusSeconds(61))}
        rejects{validateReminders(page.copy(graceSeconds=301),now)}
        rejects{validateReminders(page.copy(reminders=List(51){item}),now)}
    }
    @Test fun malformedDatesIdentityAndDuplicates(){
        rejects{validateReminders(page.copy(serverTime="invalid"),now)}
        rejects{validateReminders(page.copy(reminders=listOf(item.copy(dueAt="invalid"))),now)}
        rejects{validateReminders(page.copy(reminders=listOf(item,item)),now)}
        rejects{validateReminders(page.copy(reminders=listOf(item.copy(eventRevision=0))),now)}
        rejects{validateReminders(page.copy(reminders=listOf(item.copy(expiresAt=now.plusSeconds(301).toString()))),now)}
        rejects{validateReminders(page.copy(reminders=listOf(item.copy(due=false))),now)}
    }
    @Test fun sameTimeEditIsSameReceipt(){
        assertEquals(reminderReceipt(item),reminderReceipt(item.copy(eventRevision=2,id="rmd_"+"e".repeat(32))))
        assertNotEquals(reminderReceipt(item),reminderReceipt(item.copy(dueAt=now.plusSeconds(60).toString())))
    }
    @Test fun futureIsValidatedButNeverShown(){
        val future=item.copy(dueAt=now.plusSeconds(60).toString(),expiresAt=now.plusSeconds(360).toString(),due=false)
        assertEquals(listOf(future),validateReminders(page.copy(reminders=emptyList(),reminder=future),now))
        assertFalse(reminderMayShow(page,future,now))
        rejects{validateReminders(page.copy(reminders=listOf(item.copy(dueAt=now.plusSeconds(86401).toString(),expiresAt=now.plusSeconds(86701).toString(),due=false))),now)}
    }
}
