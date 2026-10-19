package com.shadeai.app.core.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class CoreAccessGrant(
    val id: String,
    @SerialName("notification_id") val notificationId: Long,
    @SerialName("entity_id") val entityId: String,
    @SerialName("policy_scope") val policyScope: String,
    @SerialName("duration_minutes") val durationMinutes: Int,
    val state: String,
    @SerialName("error_code") val errorCode: String? = null,
    @SerialName("event_id") val eventId: Long? = null,
    @SerialName("new_state") val newState: String? = null,
    @SerialName("state_observed") val stateObserved: Boolean,
    @SerialName("created_at") val createdAt: String,
    @SerialName("expires_at") val expiresAt: String,
    @SerialName("updated_at") val updatedAt: String,
    val pin: String? = null,
) { override fun toString() = "CoreAccessGrant(redacted)" }

@Serializable
data class CoreAccess(
    val version: Int,
    val enabled: Boolean,
    val adapter: String,
    @SerialName("policy_scope") val policyScope: String,
    @SerialName("allowed_locks") val allowedLocks: List<String>,
    @SerialName("max_minutes") val maxMinutes: Int,
    @SerialName("one_use") val oneUse: Boolean,
    @SerialName("owner_confirmation") val ownerConfirmation: Boolean,
    val grants: List<CoreAccessGrant>,
) { override fun toString() = "CoreAccess(redacted)" }

@Serializable
data class AccessCreation(
    @SerialName("notification_id") val notificationId: Long,
    @SerialName("entity_id") val entityId: String,
    @SerialName("duration_minutes") val durationMinutes: Int,
    @SerialName("policy_scope") val policyScope: String,
    val confirmed: Boolean,
    @SerialName("delivery_checked") val deliveryChecked: Boolean,
)

@Serializable
data class AccessRevocation(val checked: Boolean)

interface AccessClient {
    suspend fun descriptor(): CoreAccess
    suspend fun create(body: AccessCreation): CoreAccessGrant
    suspend fun state(id: String): CoreAccessGrant
    suspend fun revoke(id: String, body: AccessRevocation): CoreAccessGrant
}
