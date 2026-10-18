package com.shadeai.app.core.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class CoreNotification(
    val id: Long,
    @SerialName("app_name") val appName: String,
    val title: String,
    val text: String,
    val timestamp: String,
    val priority: String,
    val category: String? = null,
    @SerialName("event_id") val eventId: String? = null,
    val status: String,
    @SerialName("processing_status") val processingStatus: String? = null,
    @SerialName("processing_attempts") val processingAttempts: Int = 0,
    @SerialName("processing_error_code") val processingErrorCode: String? = null,
    @SerialName("processed_data") val processedData: JsonElement? = null,
) {
    override fun toString() = "CoreNotification(redacted)"
}

@Serializable
data class CoreNotificationsPage(val items: List<CoreNotification>, val total: Int) {
    override fun toString() = "CoreNotificationsPage(redacted)"
}

interface ResultsClient {
    suspend fun list(limit: Int, offset: Int): CoreNotificationsPage
    suspend fun detail(id: Long): CoreNotification
}
