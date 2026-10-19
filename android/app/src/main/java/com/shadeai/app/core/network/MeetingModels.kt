package com.shadeai.app.core.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class MeetingPolicy(val version:Int,val enabled:Boolean,@SerialName("allowed_targets")val allowedTargets:List<String>,@SerialName("max_duration_seconds")val maxDurationSeconds:Int)
@Serializable
data class CoreMeeting(val policy:MeetingPolicy,@SerialName("event_id")val eventId:String,@SerialName("event_revision")val eventRevision:Int,
    @SerialName("policy_scope")val policyScope:String,val eligible:Boolean,val stale:Boolean,@SerialName("starts_at")val startsAt:String,
    @SerialName("ends_at")val endsAt:String,val status:String,val targets:List<String>,@SerialName("approval_valid")val approvalValid:Boolean,
    @SerialName("started_targets")val startedTargets:List<String>)
@Serializable
data class CoreMeetingLease(@SerialName("entity_id")val entityId:String,val generation:String,val state:String,val reason:String?=null,val members:List<String>,@SerialName("updated_at")val updatedAt:String)
@Serializable
data class CoreMeetingLog(val id:Long,@SerialName("entity_id")val entityId:String,val state:String,val reason:String?=null)
@Serializable
data class CoreMeetingPage(val policy:MeetingPolicy,val leases:List<CoreMeetingLease>,val history:List<CoreMeetingLog>)
@Serializable
data class MeetingDecision(val decision:String,@SerialName("event_revision")val eventRevision:Int,@SerialName("policy_scope")val policyScope:String?=null,val targets:List<String> = emptyList())
@Serializable
data class MeetingAck(val generation:String,val checked:Boolean)
interface MeetingClient {
    suspend fun page():CoreMeetingPage
    suspend fun view(id:String):CoreMeeting
    suspend fun decide(id:String,body:MeetingDecision):CoreStatus
    suspend fun ack(entity:String,body:MeetingAck):CoreStatus
}
