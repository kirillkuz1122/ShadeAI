package com.shadeai.app

import com.shadeai.app.core.network.*
import com.shadeai.app.ui.*
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer

class MeetingTest {
    private val id="cal_"+"a".repeat(32)
    private val policy=MeetingPolicy(1,true,listOf("switch.dnd"),28800)
    private val view=CoreMeeting(policy,id,1,"b".repeat(64),true,false,"2026-10-19T04:00:00Z","2026-10-19T05:00:00Z","not_approved",emptyList(),false,emptyList())
    private val lease=CoreMeetingLease("switch.dnd","11111111-1111-1111-1111-111111111111","unknown",null,emptyList(),"2026-10-19T04:00:00Z")
    private val page=CoreMeetingPage(policy,listOf(lease),emptyList())
    private fun saved(r:String)=ResultsCredentials(r,"http://127.0.0.1:8000/","synthetic-test-key")
    @Test fun actualRetrofitReminderAndMeetingContracts()=runBlocking {
        val server=MockWebServer();server.start()
        try{
            val key="synthetic-meeting-test-key-000000001"
            val api=ShadeApi.create(server.url("/").toString(),key)
            server.enqueue(MockResponse().setBody("""{"version":1,"policy_scope":"${"b".repeat(64)}","source_id":"${"c".repeat(64)}","enabled":true,"configured":true,"stale":false,"server_time":"2026-10-19T04:00:00Z","timezone":"UTC","lead_minutes":10,"grace_seconds":300,"reminder":{"id":"rmd_${"d".repeat(32)}","event_id":"$id","event_revision":1,"due_at":"2026-10-19T04:00:00Z","expires_at":"2026-10-19T04:05:00Z","due":true}}"""))
            assertEquals(id,api.reminder("rmd_"+"d".repeat(32)).reminder!!.eventId)
            server.enqueue(MockResponse().setBody("""{"status":"disabled"}"""))
            assertEquals("disabled",api.decideMeeting(id,MeetingDecision("disable",1)).status)
            server.enqueue(MockResponse().setBody("""{"status":"acknowledged"}"""))
            assertEquals("acknowledged",api.acknowledgeMeeting("switch.dnd",MeetingAck(lease.generation,true)).status)
            val first=server.takeRequest();assertEquals("Bearer $key",first.getHeader("Authorization"));assertEquals("/api/v1/calendar/reminders/rmd_"+"d".repeat(32),first.path)
            val second=server.takeRequest();assertEquals("POST",second.method);assertEquals("/api/v1/calendar/events/$id/meeting",second.path)
            assertEquals("""{"decision":"disable","event_revision":1}""",second.body.readUtf8())
            val third=server.takeRequest();assertEquals("/api/v1/calendar/meeting/leases/switch.dnd/ack",third.path)
            val body=third.body.readUtf8();assertEquals("""{"generation":"${lease.generation}","checked":true}""",body);assertFalse(body.contains(key))
        }finally{server.shutdown()}
    }
    @Test fun validatesPolicyAndBoundedHistory(){
        assertTrue(knownMeeting(view));assertTrue(knownMeetingPage(page))
        assertFalse(knownMeeting(view.copy(policy=policy.copy(version=2))))
        assertFalse(knownMeeting(view.copy(policyScope="bad")))
        assertFalse(knownMeetingPage(page.copy(leases=listOf(lease.copy(state="future-private")))))
        assertFalse(knownMeetingPage(page.copy(leases=listOf(lease.copy(generation="bad")))))
    }
    @Test fun explicitScopeAndSelectionAndAckArePinned()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val decisions=mutableListOf<MeetingDecision>();val acks=mutableListOf<MeetingAck>()
        val c=MeetingController(scope,{saved("same")},{"same"}){object:MeetingClient{
            override suspend fun page()=page
            override suspend fun view(id:String)=view
            override suspend fun decide(id:String,body:MeetingDecision):CoreStatus{decisions.add(body);return CoreStatus("approved")}
            override suspend fun ack(entity:String,body:MeetingAck):CoreStatus{acks.add(body);return CoreStatus("acknowledged")}
        }}
        try{
            c.start();c.select(id);yield()
            c.decide(true,listOf("switch.forbidden"));c.decide(true);yield();assertTrue(decisions.isEmpty())
            c.decide(true,listOf("switch.dnd"));yield();assertEquals(view.policyScope,decisions.single().policyScope)
            c.acknowledge("switch.dnd",lease.generation,false);c.acknowledge("switch.dnd","wrong",true);yield();assertTrue(acks.isEmpty())
            c.acknowledge("switch.dnd",lease.generation,true);yield();assertTrue(acks.single().checked)
        }finally{c.close();scope.cancel()}
    }
    @Test fun staleCanDisableButCannotApprove()=runBlocking{
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val decisions=mutableListOf<MeetingDecision>()
        val c=MeetingController(scope,{saved("same")},{"same"}){object:MeetingClient{
            override suspend fun page()=page
            override suspend fun view(id:String)=view.copy(stale=true)
            override suspend fun decide(id:String,body:MeetingDecision):CoreStatus{decisions.add(body);return CoreStatus("disabled")}
            override suspend fun ack(entity:String,body:MeetingAck)=CoreStatus("acknowledged")
        }}
        try{c.start();c.select(id);yield();c.decide(true,listOf("switch.dnd"));yield();assertTrue(decisions.isEmpty());c.decide(false);yield();assertEquals("disable",decisions.single().decision);assertNull(decisions.single().policyScope)
        }finally{c.close();scope.cancel()}
    }
    @Test fun changedConnectionNeverReceivesOldConsent()=runBlocking{
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);var revision="old";var calls=0
        val c=MeetingController(scope,{saved(revision)},{revision}){object:MeetingClient{
            override suspend fun page()=page
            override suspend fun view(id:String)=view
            override suspend fun decide(id:String,body:MeetingDecision):CoreStatus{calls++;return CoreStatus("approved")}
            override suspend fun ack(entity:String,body:MeetingAck)=CoreStatus("acknowledged")
        }}
        try{c.start();c.select(id);yield();revision="new";c.decide(true,listOf("switch.dnd"));yield();assertEquals(0,calls);assertTrue(c.state.value.message!!.contains("изменились"))
        }finally{c.close();scope.cancel()}
    }
    @Test fun lateResponseAfterStopCannotRestoreState()=runBlocking{
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val pending=CompletableDeferred<CoreMeetingPage>()
        val c=MeetingController(scope,{saved("same")},{"same"}){object:MeetingClient{
            override suspend fun page()=withContext(NonCancellable){pending.await()}
            override suspend fun view(id:String)=view
            override suspend fun decide(id:String,body:MeetingDecision)=CoreStatus("approved")
            override suspend fun ack(entity:String,body:MeetingAck)=CoreStatus("acknowledged")
        }}
        try{c.start();yield();c.close();pending.complete(page);yield();assertNull(c.state.value.page);assertNull(c.state.value.view)
        }finally{pending.complete(page);scope.cancel()}
    }
}
