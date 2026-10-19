package com.shadeai.app.core.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class VoiceTarget(val alias:String,@SerialName("entity_id")val entityId:String)
@Serializable
data class CoreVoiceRequest(val id:String,@SerialName("policy_scope")val policyScope:String,
    @SerialName("entity_id")val entityId:String,val action:String,val alias:String,val state:String,
    @SerialName("error_code")val errorCode:String?=null,@SerialName("event_id")val eventId:Long?=null,
    @SerialName("new_state")val newState:String?=null,@SerialName("state_observed")val stateObserved:Boolean,
    @SerialName("created_at")val createdAt:String,@SerialName("expires_at")val expiresAt:String,
    @SerialName("updated_at")val updatedAt:String,val transcription:String?=null){override fun toString()="CoreVoiceRequest(redacted)"}
@Serializable
data class CoreVoice(val version:Int,val enabled:Boolean,@SerialName("policy_scope")val policyScope:String,
    @SerialName("stt_available")val sttAvailable:Boolean,@SerialName("stt_status")val sttStatus:String,
    @SerialName("requires_confirmation")val requiresConfirmation:Boolean,@SerialName("max_audio_seconds")val maxAudioSeconds:Int,
    val targets:List<VoiceTarget>,val requests:List<CoreVoiceRequest>){override fun toString()="CoreVoice(redacted)"}
@Serializable
data class VoiceConfirmation(@SerialName("policy_scope")val policyScope:String,val confirmed:Boolean)
interface VoiceClient {
    suspend fun descriptor():CoreVoice
    suspend fun prepare(id:String,wav:ByteArray):CoreVoiceRequest
    suspend fun state(id:String):CoreVoiceRequest
    suspend fun confirm(id:String,body:VoiceConfirmation):CoreVoiceRequest
    suspend fun cancel(id:String):CoreVoiceRequest
}
