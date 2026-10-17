package com.shadeai.app.core.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class AccessResponse(val total: Long)

@Serializable
data class HealthResponse(
    val status: String,
    val uptime: Long,
    @SerialName("ha_connected") val haConnected: Boolean,
    @SerialName("llm_status") val llmStatus: String,
    @SerialName("db_size") val dbSize: String,
    @SerialName("db_connected") val dbConnected: Boolean = false,
    @SerialName("db_size_bytes") val dbSizeBytes: Long? = null,
    @SerialName("ha_status") val haStatus: String = "unknown",
    val services: Map<String, String> = emptyMap(),
)

@Serializable
data class NotificationIngest(
    @SerialName("app_name") val appName: String,
    val title: String,
    val text: String,
    val timestamp: String,
    val priority: String = "default",
    @SerialName("event_id") val eventId: String? = null,
)

@Serializable
data class IngestResponse(
    val id: Long?,
    val status: String,
    val reason: String? = null,
)
