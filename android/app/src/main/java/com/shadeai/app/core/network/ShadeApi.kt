package com.shadeai.app.core.network

import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import com.shadeai.app.core.config.ServerAddress
import kotlinx.serialization.json.Json
import okhttp3.ConnectionPool
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.Header
import okhttp3.RequestBody
import java.io.IOException
import java.net.Proxy
import java.util.concurrent.TimeUnit

class MissingCredentialsException : IOException("Не задан ключ Core")

interface ShadeApi {
    @GET("voice")
    suspend fun voice():CoreVoice
    @POST("voice")
    suspend fun prepareVoice(@Header("X-Request-ID")id:String,@Body wav:RequestBody):CoreVoiceRequest
    @GET("voice/{id}")
    suspend fun voiceState(@Path("id")id:String):CoreVoiceRequest
    @POST("voice/{id}/confirm")
    suspend fun confirmVoice(@Path("id")id:String,@Body body:VoiceConfirmation):CoreVoiceRequest
    @POST("voice/{id}/cancel")
    suspend fun cancelVoice(@Path("id")id:String):CoreVoiceRequest

    @GET("calendar/meeting")
    suspend fun meetingState():CoreMeetingPage
    @GET("calendar/events/{id}/meeting")
    suspend fun meeting(@Path("id")id:String):CoreMeeting
    @POST("calendar/events/{id}/meeting")
    suspend fun decideMeeting(@Path("id")id:String,@Body body:MeetingDecision):CoreStatus
    @POST("calendar/meeting/leases/{entity}/ack")
    suspend fun acknowledgeMeeting(@Path("entity")entity:String,@Body body:MeetingAck):CoreStatus

    @GET("calendar/reminders")
    suspend fun reminders():CoreReminderPage
    @GET("calendar/reminders/{id}")
    suspend fun reminder(@Path("id")id:String):CoreReminderPage


    @GET("calendar/events")
    suspend fun calendar(@Query("offset")offset:Int,@Query("include_inactive")inactive:Boolean,@Query("limit")limit:Int=50):CoreCalendarPage
    @POST("calendar/sync")
    suspend fun syncCalendar():CoreStatus

    @GET("health")
    suspend fun health(): HealthResponse

    @GET("notifications?limit=1")
    suspend fun verifyAccess(): AccessResponse

    @POST("notifications")
    suspend fun ingest(@Body body: NotificationIngest): IngestResponse

    @GET("notifications")
    suspend fun notifications(@Query("limit") limit: Int, @Query("offset") offset: Int): CoreNotificationsPage

    @GET("notifications/{id}")
    suspend fun notification(@Path("id") id: Long): CoreNotification

    @GET("automations")
    suspend fun automations(@Query("offset") offset: Int, @Query("limit") limit: Int = 20): CoreRulesPage

    @GET("automations/{id}")
    suspend fun automation(@Path("id") id: String): CoreRule

    @POST("automations/{id}/decision")
    suspend fun decideAutomation(@Path("id") id: String, @Body body: RuleDecision): CoreRule

    @POST("automations/refresh")
    suspend fun refreshAutomations(): CoreStatus

    @GET("hints")
    suspend fun hints(@Query("after_id") afterId: Long = 0, @Query("limit") limit: Int = 20): CoreHintFeed

    companion object {
        private val transport = OkHttpClient.Builder()
            .connectTimeout(3, TimeUnit.SECONDS)
            .readTimeout(5, TimeUnit.SECONDS)
            .writeTimeout(5, TimeUnit.SECONDS)
            .callTimeout(10, TimeUnit.SECONDS)
            .followRedirects(false)
            .followSslRedirects(false)
            .retryOnConnectionFailure(false)
            .proxy(Proxy.NO_PROXY)
            // Без retry не переиспользуем простаивающий сокет, уже закрытый Core.
            .connectionPool(ConnectionPool(0, 1, TimeUnit.MINUTES))
            .build()

        fun create(baseUrl: String, apiKey: String, voice:Boolean=false): ShadeApi {
            require(apiKey.isEmpty() || ServerAddress.validKey(apiKey)) { "Некорректный ключ Core" }
            val url = ServerAddress.normalize(baseUrl).toHttpUrl()
            val builder = transport.newBuilder()
            if(voice)builder.callTimeout(45,TimeUnit.SECONDS).readTimeout(40,TimeUnit.SECONDS)
            val client = builder.addInterceptor { chain ->
                val request = chain.request()
                if (request.url.scheme != url.scheme || request.url.host != url.host || request.url.port != url.port) {
                    throw IOException("Адрес запроса отличается от настроенного Core")
                }
                val builder = request.newBuilder().removeHeader("Authorization")
                if (request.url.encodedPath != url.encodedPath + "health") {
                    if (apiKey.isBlank()) throw MissingCredentialsException()
                    builder.header("Authorization", "Bearer $apiKey")
                }
                chain.proceed(builder.build())
            }.build()
            val json = Json { ignoreUnknownKeys = true }
            return Retrofit.Builder()
                .baseUrl(url)
                .client(client)
                .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
                .build()
                .create(ShadeApi::class.java)
        }
    }
}
