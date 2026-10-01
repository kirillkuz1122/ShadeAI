package com.shadeai.app.core.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class HealthResponse(
    val status: String,
    val uptime: Long,
    @SerialName("ha_connected") val haConnected: Boolean,
    @SerialName("llm_status") val llmStatus: String,
    @SerialName("db_size") val dbSize: String,
)

@Serializable
data class NotificationIngest(
    @SerialName("app_name") val appName: String,
    val title: String,
    val text: String,
    val timestamp: String,
    val priority: String = "default",
)

@Serializable
data class IngestResponse(
    val id: Long,
    val status: String,
)
