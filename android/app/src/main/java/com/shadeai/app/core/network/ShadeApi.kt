package com.shadeai.app.core.network

import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import retrofit2.Retrofit
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST

interface ShadeApi {

    @GET("health")
    suspend fun health(): HealthResponse

    @POST("notifications")
    suspend fun ingest(@Body body: NotificationIngest): IngestResponse

    companion object {
        fun create(baseUrl: String): ShadeApi {
            val json = Json { ignoreUnknownKeys = true }
            return Retrofit.Builder()
                .baseUrl(baseUrl)
                .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
                .build()
                .create(ShadeApi::class.java)
        }
    }
}
