package com.shadeai.app

import com.shadeai.app.core.network.*
import com.shadeai.app.ui.*
import com.shadeai.app.voice.*
import kotlinx.coroutines.*
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.time.Instant
import java.util.UUID

class VoiceTest {
    private val now=Instant.now()
    private val hash="a".repeat(64)
    private fun request(id:String=UUID.randomUUID().toString(),state:String="pending")=CoreVoiceRequest(id,hash,"light.test","turn_on","свет на кухне",state,stateObserved=false,createdAt=now.toString(),expiresAt=now.plusSeconds(60).toString(),updatedAt=now.toString(),transcription="private synthetic voice")
    private fun page()=CoreVoice(1,true,hash,true,"configured",true,10,listOf(VoiceTarget("свет на кухне","light.test")),emptyList())
    private fun saved(revision:String)=ResultsCredentials(revision,"http://127.0.0.1:8000/","synthetic-voice-key-000000000001")
    private open class Recorder:VoiceRecorder {
        var stopped=0
        override suspend fun record()=pcmWave(ByteArray(8000){1})
        override fun stop(){stopped++}
    }
    private open inner class Client:VoiceClient {
        var sent=0;var confirmations=0;var last:CoreVoiceRequest?=null;var body:VoiceConfirmation?=null
        override suspend fun descriptor()=page()
        override suspend fun prepare(id:String,wav:ByteArray):CoreVoiceRequest{sent++;return request(id).also{last=it}}
        override suspend fun state(id:String)=requireNotNull(last).copy(state="accepted",transcription=null)
        override suspend fun confirm(id:String,body:VoiceConfirmation):CoreVoiceRequest{confirmations++;this.body=body;return requireNotNull(last).copy(state="accepted",transcription=null)}
        override suspend fun cancel(id:String)=requireNotNull(last).copy(state="cancelled",transcription=null)
    }
    @Test fun wavHeaderIsActualPcm16Mono16kAndBounded(){
        val pcm=ByteArray(320000){1};val wav=pcmWave(pcm,8000)
        assertEquals(8044,wav.size);assertEquals("RIFF",wav.copyOfRange(0,4).toString(Charsets.US_ASCII))
        val data=ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN)
        assertEquals(wav.size-8,data.getInt(4));assertEquals(16000,data.getInt(24));assertEquals(8000,data.getInt(40))
        for(size in listOf(7998,320002,8001))try{pcmWave(ByteArray(size));fail()}catch(_:IllegalArgumentException){}
    }
    @Test fun policyAndRequestGuardsRejectUnknownTargetsAndStates(){
        assertTrue(knownVoice(page()));assertTrue(knownVoiceRequest(request()))
        assertFalse(knownVoice(page().copy(version=2)));assertFalse(knownVoice(page().copy(requiresConfirmation=false)))
        assertFalse(knownVoiceRequest(request().copy(entityId="lock.front")))
        assertFalse(knownVoiceRequest(request().copy(state="private-future")))
        assertFalse(knownVoiceRequest(request().copy(expiresAt="invalid")))
        assertFalse(request().toString().contains("private"))
    }
    @Test fun recordingNeverExecutesWithoutExplicitCurrentScopeConfirmation()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val client=Client();val recorder=Recorder()
        val c=VoiceController(scope,{saved("same")},{"same"},{client},recorder)
        try{
            c.start();yield();c.record("same");yield();assertEquals(1,client.sent);assertEquals(0,client.confirmations)
            assertEquals("ready",c.state.value.phase);c.confirm();yield()
            assertEquals(1,client.confirmations);assertEquals(hash,client.body!!.policyScope);assertTrue(client.body!!.confirmed)
            c.confirm();yield();assertEquals(1,client.confirmations)
        }finally{c.close();scope.cancel()}
    }
    @Test fun lateAudioAfterStopCannotSendOrRestorePayload()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val gate=CompletableDeferred<ByteArray>();val client=Client()
        val c=VoiceController(scope,{saved("same")},{"same"},{client},object:Recorder(){override suspend fun record()=withContext(NonCancellable){gate.await()}})
        val wav=pcmWave(ByteArray(8000){1})
        try{c.start();yield();c.record("same");yield();c.close();gate.complete(wav);yield();assertEquals(0,client.sent);assertNull(c.state.value.request);assertNull(c.state.value.page);assertTrue(wav.all{it==0.toByte()})
        }finally{gate.complete(wav);scope.cancel()}
    }
    @Test fun changedConnectionBeforeSendOrConfirmNeverReceivesOldConsent()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val client=Client();var revision="old"
        val c=VoiceController(scope,{saved(revision)},{revision},{client},Recorder())
        try{c.start();yield();c.record("old");yield();revision="new";c.confirm();yield();assertEquals(0,client.confirmations);assertNull(c.state.value.request)
        }finally{c.close();scope.cancel()}
    }
    @Test fun uncertainConfirmationCannotAutomaticallyRetry()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
        val client=object:Client(){override suspend fun confirm(id:String,body:VoiceConfirmation):CoreVoiceRequest{confirmations++;throw java.io.IOException("private raw error")}}
        val c=VoiceController(scope,{saved("same")},{"same"},{client},Recorder())
        try{c.start();yield();c.record("same");yield();c.confirm();yield();assertEquals("uncertain",c.state.value.phase);c.confirm();yield();assertEquals(1,client.confirmations);assertFalse(c.state.value.error!!.contains("private"));c.checkStatus();yield();assertEquals("accepted",c.state.value.request!!.state)
        }finally{c.close();scope.cancel()}
    }
    @Test fun requestPermissionRevisionCannotBeTransferred()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val client=Client()
        val c=VoiceController(scope,{saved("new")},{"new"},{client},Recorder())
        try{c.start();yield();c.record("old");yield();assertEquals(0,client.sent)
        }finally{c.close();scope.cancel()}
    }
    @Test fun cancelledPreparationNeverStartsMicrophone()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val client=Client();var reads=0;var recordings=0
        val gate=CompletableDeferred<ResultsCredentials>()
        val c=VoiceController(scope,{reads++;if(reads==1)saved("same")else withContext(NonCancellable){gate.await()}},{"same"},{client},object:Recorder(){override suspend fun record():ByteArray{recordings++;return super.record()}})
        try{c.start();yield();c.record("same");yield();assertEquals("preparing",c.state.value.phase);c.cancelCapture();gate.complete(saved("same"));yield();assertEquals(0,recordings);assertEquals(0,client.sent)
        }finally{gate.complete(saved("same"));c.close();scope.cancel()}
    }
    @Test fun authFailureClearsTranscriptAndOldConnectionData()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
        val client=object:Client(){override suspend fun prepare(id:String,wav:ByteArray):CoreVoiceRequest{throw retrofit2.HttpException(retrofit2.Response.error<CoreVoiceRequest>(401,"private raw".toResponseBody()))}}
        val c=VoiceController(scope,{saved("same")},{"same"},{client},Recorder())
        try{c.start();yield();c.record("same");yield();assertNull(c.state.value.page);assertNull(c.state.value.request);assertFalse(c.state.value.error!!.contains("private"))
        }finally{c.close();scope.cancel()}
    }
    @Test fun retrofitUploadsRawWavWithBearerAndExplicitConfirmation()=runBlocking {
        val server=MockWebServer();server.start()
        try{
            val id=UUID.randomUUID().toString();val row=request(id);val key="synthetic-voice-key-000000000001"
            server.enqueue(MockResponse().setBody(Json.encodeToString(row)))
            server.enqueue(MockResponse().setBody(Json.encodeToString(row.copy(state="accepted"))))
            val api=ShadeApi.create(server.url("/").toString(),key,voice=true)
            val wav=pcmWave(ByteArray(8000){1})
            assertTrue(knownVoiceRequest(api.prepareVoice(id,wav.toRequestBody("audio/wav".toMediaType()))))
            api.confirmVoice(id,VoiceConfirmation(hash,true))
            val first=server.takeRequest();assertEquals("/api/v1/voice",first.path);assertEquals("Bearer $key",first.getHeader("Authorization"));assertEquals(id,first.getHeader("X-Request-ID"));assertArrayEquals(wav,first.body.readByteArray())
            val second=server.takeRequest();assertEquals("/api/v1/voice/$id/confirm",second.path)
            assertEquals("""{"policy_scope":"$hash","confirmed":true}""",second.body.readUtf8())
        }finally{server.shutdown()}
    }
}
