package com.shadeai.app

import com.shadeai.app.core.network.*
import com.shadeai.app.ui.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import java.time.Instant
import java.util.UUID

class AccessControllerTest {
    private val hash="a".repeat(64)
    private val now=Instant.now()
    private val parsed=Json.parseToJsonElement("""{"processor":"llm","llm":true,"schema_version":1,"action_authorized":false,"category":"delivery","intent":"delivery_event","priority":"default","entities":{"subject":"Посылка","location":null,"service":null},"time":{"source":null,"timezone":"UTC","at":null,"date":null,"resolution":"absent"}}""")
    private fun source()=CoreNotification(42,"ru.ozon.app.android","Синтетическая доставка","private synthetic delivery",now.minusSeconds(1).toString(),"default",category="delivery",status="processed",processingStatus="processed",processedData=parsed)
    private fun grant()=CoreAccessGrant(UUID.randomUUID().toString(),42,"lock.test",hash,5,"active",stateObserved=false,createdAt=now.toString(),expiresAt=now.plusSeconds(300).toString(),updatedAt=now.toString(),pin="012345")
    private fun page()=CoreAccess(1,true,"shade_keypad",hash,listOf("lock.test"),15,true,true,emptyList())
    private fun saved(rev:String)=ResultsCredentials(rev,"http://127.0.0.1:8000/","synthetic-access-owner-key-000000001")
    private open inner class Client:AccessClient {
        var calls=0;var revoked=0;var sent:AccessCreation?=null;var revocation:AccessRevocation?=null
        var current=grant();var descriptorPage=page()
        override suspend fun descriptor()=descriptorPage
        override suspend fun create(body:AccessCreation):CoreAccessGrant {calls++;sent=body;return current}
        override suspend fun state(id:String)=current.copy(pin=null)
        override suspend fun revoke(id:String,body:AccessRevocation):CoreAccessGrant {revoked++;revocation=body;return current.copy(pin=null,state="revoked")}
    }
    private open inner class Results:ResultsClient {
        var current=source()
        override suspend fun list(limit:Int,offset:Int)=CoreNotificationsPage(listOf(current),1)
        override suspend fun detail(id:Long)=current
    }
    private fun ready(c:AccessController) {c.start(true);c.selectSource(42);c.target("lock.test");c.deliveryChecked(true);c.unlockChecked(true)}

    @Test fun createNeedsProtectedWindowSelectedSourceTargetAndTwoConsents()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val api=Client();val rows=Results()
        val c=AccessController(scope,{saved("same")},{"same"},{api},{rows})
        try {
            c.start(false);c.create();assertNull(c.state.value.page);assertEquals(0,api.calls)
            c.start(true);c.selectSource(999);assertNull(c.state.value.source)
            c.selectSource(42);c.deliveryChecked(true);c.unlockChecked(true);c.create();assertEquals(0,api.calls)
            c.target("lock.test");assertFalse(c.state.value.deliveryChecked);assertFalse(c.state.value.unlockChecked)
            c.deliveryChecked(true);c.create();assertEquals(0,api.calls)
            c.unlockChecked(true);c.create();assertEquals(1,api.calls)
            assertTrue(api.sent!!.confirmed && api.sent!!.deliveryChecked)
            assertEquals("012345",c.state.value.grant!!.pin);assertFalse(c.state.value.toString().contains("012345"))
            assertNull(c.state.value.page!!.grants[0].pin)
            c.create();c.selectSource(42);c.target("lock.test");c.deliveryChecked(true);c.unlockChecked(true);c.create()
            assertEquals(1,api.calls)
        } finally {c.close();scope.cancel()}
    }
    @Test fun selectionAndDurationChangesDiscardConsentAndPin()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val api=Client();val rows=Results()
        val c=AccessController(scope,{saved("same")},{"same"},{api},{rows})
        try {ready(c);c.minutes(6);assertFalse(c.state.value.deliveryChecked);c.create();assertEquals(0,api.calls)
            c.deliveryChecked(true);c.unlockChecked(true);c.selectSource(42);assertNull(c.state.value.target)
            c.close();assertNull(c.state.value.source);assertNull(c.state.value.page);assertNull(c.state.value.grant)
        } finally {c.close();scope.cancel()}
    }
    @Test fun lateCreateAfterPauseCannotRestorePin()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val gate=CompletableDeferred<CoreAccessGrant>()
        val api=object:Client(){override suspend fun create(body:AccessCreation):CoreAccessGrant {calls++;return withContext(NonCancellable){gate.await()}}}
        val c=AccessController(scope,{saved("same")},{"same"},{api},{Results()})
        try {ready(c);c.create();assertEquals(1,api.calls);c.close();gate.complete(grant());yield();assertNull(c.state.value.grant);assertNull(c.state.value.source)
        } finally {gate.complete(grant());scope.cancel()}
    }
    @Test fun revisionChangeAndPolicyChangePreventOldApproval()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val api=Client();var rev="old"
        val c=AccessController(scope,{saved(rev)},{rev},{api},{Results()})
        try {ready(c);rev="new";c.create();assertEquals(0,api.calls);assertNull(c.state.value.source)
            c.start(true);c.selectSource(42);c.target("lock.test");c.deliveryChecked(true);c.unlockChecked(true)
            api.descriptorPage=page().copy(policyScope="b".repeat(64));c.create();assertEquals(0,api.calls);assertNull(c.state.value.source)
        } finally {c.close();scope.cancel()}
    }
    @Test fun changedSourceMustBeReviewedAgain()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val api=Client();val rows=Results()
        val c=AccessController(scope,{saved("same")},{"same"},{api},{rows})
        try {ready(c);rows.current=source().copy(text="Changed delivery");c.create();assertEquals(0,api.calls);assertNull(c.state.value.source)
        } finally {c.close();scope.cancel()}
    }
    @Test fun lostCreateResponseNeverAutomaticallyRetriesAndClearsPrivateReview()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
        val api=object:Client(){override suspend fun create(body:AccessCreation):CoreAccessGrant {calls++;throw java.io.IOException("private raw failure")}}
        val c=AccessController(scope,{saved("same")},{"same"},{api},{Results()})
        try {ready(c);c.create();assertEquals("uncertain",c.state.value.phase);assertNull(c.state.value.source);assertFalse(c.state.value.error!!.contains("private"));c.create();assertEquals(1,api.calls)
            c.refresh();assertEquals(1,api.calls);assertNull(c.state.value.grant)
        } finally {c.close();scope.cancel()}
    }
    @Test fun unauthorizedResponseClearsEverything()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
        val api=object:Client(){override suspend fun create(body:AccessCreation):CoreAccessGrant {throw HttpException(Response.error<CoreAccessGrant>(401,"private".toResponseBody("text/plain".toMediaType())))}}
        val c=AccessController(scope,{saved("same")},{"same"},{api},{Results()})
        try {ready(c);c.create();assertNull(c.state.value.page);assertNull(c.state.value.source);assertNull(c.state.value.grant)
        } finally {c.close();scope.cancel()}
    }
    @Test fun unknownRequiresManualCheckAndRevokeDoesNotClaimDoorLocked()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val api=Client()
        api.current=grant().copy(state="unknown",pin=null);api.descriptorPage=page().copy(grants=listOf(api.current))
        val c=AccessController(scope,{saved("same")},{"same"},{api},{Results()})
        try {c.start(true);c.selectGrant(api.current.id);c.revoke();assertEquals(0,api.revoked)
            c.manualChecked(true);c.revoke();assertEquals(1,api.revoked);assertTrue(api.revocation!!.checked)
            assertEquals("revoked",c.state.value.grant!!.state);assertNull(c.state.value.grant!!.newState)
        } finally {c.close();scope.cancel()}
    }
    @Test fun historyAndStatusCannotInjectPin()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val api=Client()
        api.descriptorPage=page().copy(grants=listOf(grant()))
        val c=AccessController(scope,{saved("same")},{"same"},{api},{Results()})
        try {c.start(true);assertNull(c.state.value.page);assertNull(c.state.value.grant)
        } finally {c.close();scope.cancel()}
    }
    @Test fun changedRevisionDuringLateResponseClearsOldStateWithoutPrefsCallback()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);var rev="old"
        val gate=CompletableDeferred<CoreAccessGrant>()
        val api=object:Client(){override suspend fun create(body:AccessCreation)=withContext(NonCancellable){gate.await()}}
        val c=AccessController(scope,{saved(rev)},{rev},{api},{Results()})
        try {ready(c);c.create();rev="new";gate.complete(grant());yield()
            assertNull(c.state.value.page);assertNull(c.state.value.source);assertNull(c.state.value.grant)
        } finally {gate.complete(grant());c.close();scope.cancel()}
    }

}

