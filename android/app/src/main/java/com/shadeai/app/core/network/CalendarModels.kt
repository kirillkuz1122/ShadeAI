package com.shadeai.app.core.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class CoreCalendarEvent(val id:String,val summary:String,val location:String?=null,
    @SerialName("starts_at")val startsAt:String,@SerialName("ends_at")val endsAt:String,
    @SerialName("start_date")val startDate:String?=null,@SerialName("end_date")val endDate:String?=null,
    @SerialName("all_day")val allDay:Boolean,val status:String,val busy:Boolean,val revision:Int,
    @SerialName("updated_at")val updatedAt:String) {override fun toString()="CoreCalendarEvent(redacted)"}
@Serializable
data class CoreCalendarPage(val status:String,val configured:Boolean,val stale:Boolean,val timezone:String,
    @SerialName("last_success")val lastSuccess:String?=null,val events:List<CoreCalendarEvent>,val total:Int
) {override fun toString()="CoreCalendarPage(redacted)"}
interface CalendarClient {
    suspend fun page(offset:Int,inactive:Boolean):CoreCalendarPage
    suspend fun sync():CoreStatus
}
