package com.shadeai.app.reminders

import com.shadeai.app.core.network.CoreReminder
import com.shadeai.app.core.network.CoreReminderPage
import java.time.Duration
import java.time.Instant

fun validateReminders(page:CoreReminderPage,now:Instant):List<CoreReminder> = try {
    require(page.version==1 && page.policyScope.matches(Regex("[a-f0-9]{64}")) && page.sourceId.matches(Regex("[a-f0-9]{64}")))
    require(page.graceSeconds==300 && page.leadMinutes in 1..120 && page.reminders.size<=50)
    val server=Instant.parse(page.serverTime)
    require(Duration.between(server,now).abs().seconds<=60) {"clock"}
    val items=page.reminder?.let { listOf(it) } ?: page.reminders
    require(items.map{it.id}.distinct().size==items.size)
    items.forEach {
        require(it.id.matches(Regex("rmd_[a-f0-9]{32}")) && it.eventId.matches(Regex("cal_[a-f0-9]{32}")) && it.eventRevision>0)
        val due=Instant.parse(it.dueAt);val expires=Instant.parse(it.expiresAt)
        require(Duration.between(due,expires).seconds==300L && !due.isAfter(server.plusSeconds(86400)))
        require(expires.isAfter(server) && it.due==!due.isAfter(server))
    }
    items
} catch(_:java.time.DateTimeException){throw IllegalArgumentException("format_clock")}
fun reminderReceipt(item:CoreReminder)=item.eventId+":"+Instant.parse(item.dueAt).epochSecond
fun reminderMayShow(page:CoreReminderPage,item:CoreReminder,now:Instant):Boolean =
    page.enabled && page.configured && !page.stale && !page.overflow && item.due &&
        !now.isBefore(Instant.parse(item.dueAt)) && now.isBefore(Instant.parse(item.expiresAt))
