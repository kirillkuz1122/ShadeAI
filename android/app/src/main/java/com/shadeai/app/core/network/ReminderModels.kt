package com.shadeai.app.core.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class CoreReminder(val id:String,@SerialName("event_id")val eventId:String,
    @SerialName("event_revision")val eventRevision:Int,@SerialName("due_at")val dueAt:String,
    @SerialName("expires_at")val expiresAt:String,val due:Boolean)
@Serializable
data class CoreReminderPage(val version:Int,@SerialName("policy_scope")val policyScope:String,
    @SerialName("source_id")val sourceId:String,val enabled:Boolean,val configured:Boolean,val stale:Boolean,
    @SerialName("server_time")val serverTime:String,val timezone:String,
    @SerialName("lead_minutes")val leadMinutes:Int,@SerialName("grace_seconds")val graceSeconds:Int,
    val overflow:Boolean=false,val reminders:List<CoreReminder> = emptyList(),val reminder:CoreReminder?=null)
