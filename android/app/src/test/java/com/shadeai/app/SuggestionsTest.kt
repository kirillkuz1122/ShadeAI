package com.shadeai.app

import com.shadeai.app.core.network.*
import com.shadeai.app.hints.*
import com.shadeai.app.ui.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import java.time.Instant

class SuggestionsTest {
    private val feed="11111111-1111-4111-8111-111111111111"
    private val now=Instant.parse("2026-10-19T01:00:00Z")
    private fun hint(id:Long=1,kind:String="arrival_delivery",at:String=now.toString())=CoreHint(id,kind,1,at)
    private fun rule()=CoreRule("aut_"+"a".repeat(32),"hbt_"+"b".repeat(32),"Контрольный сценарий","pending",1,
        CoreRuleTrigger("presence_transition","arrival_home","binary_sensor.test","off","on","weekdays","UTC","17:15","18:45",false),
        evidence=CoreRuleEvidence(12,15,5.0),confidence=0.8,sourceCurrent=true,approvalValid=false,enabled=false,executable=false,
        executorStatus="not_implemented",createdAt=now.toString(),updatedAt=now.toString())
    private fun page(row:CoreRule)=CoreRulesPage(listOf(row),1,listOf("light.test"),"ready","not_implemented")
    private fun credentials(revision:String)=ResultsCredentials(revision,"http://127.0.0.1/api/v1/","private-synthetic-key")
    private fun emptyFeed()=CoreHintFeed(feed,0,0,emptyList())
    @Test fun executionPolicyMustBeKnownAndBoundedBeforeConsent() {
        val current=com.shadeai.app.core.network.CoreExecutionPolicy(1,true,"binary_sensor.house",30,1800,300,90)
        assertTrue(knownRule(rule().copy(executorStatus="ready",executionPolicy=current,approvalScope="a".repeat(64))))
        assertFalse(knownRule(rule().copy(executorStatus="ready")))
        assertFalse(knownRule(rule().copy(executionPolicy=current.copy(version=2))))
        assertFalse(knownRule(rule().copy(executionPolicy=current.copy(cancelSeconds=0))))
    }
    @Test fun onlyKnownConditionsAndActionsCanBeApproved() {
        val row=rule();assertTrue(knownRule(row))
        for(bad in listOf(row.copy(confidence=Double.NaN),row.copy(status="private-status"),
            row.copy(trigger=row.trigger.copy(toState="off")),row.copy(trigger=row.trigger.copy(timezone="private-zone")),
            row.copy(action=CoreRuleAction("lock.private","turn_on",buildJsonObject{})),
            row.copy(action=CoreRuleAction("light.test","turn_off",buildJsonObject{})),
            row.copy(action=CoreRuleAction("light.test","turn_on",buildJsonObject{put("brightness",255)})),
            row.copy(evidence=CoreRuleEvidence(16,15,0.0)))) assertFalse(knownRule(bad))
    }
    @Test fun newFeedAndRollbackBootstrapWithoutNotifyingOldMessages() {
        val data=CoreHintFeed(feed,100,20,listOf(hint()))
        val plan=planHints(data,HintCursor(null,0),now)
        assertEquals(100L,plan.next.id);assertTrue(plan.show.isEmpty())
        assertTrue(planHints(data,HintCursor("22222222-2222-4222-8222-222222222222",50),now).show.isEmpty())
        assertTrue(planHints(CoreHintFeed(feed,1,100,emptyList()),HintCursor(feed,100),now).show.isEmpty())
    }
    @Test fun cursorDeliversOnlyFreshKnownHintsAndDoesNotDuplicate() {
        val data=CoreHintFeed(feed,3,3,listOf(hint(1),hint(2,"new-type"),hint(3,at=now.minusSeconds(90000).toString())))
        val plan=planHints(data,HintCursor(feed,0),now)
        assertEquals(listOf(1L),plan.show.map{it.id});assertEquals(3L,plan.next.id)
        assertTrue(planHints(CoreHintFeed(feed,3,3,emptyList()),plan.next,now).show.isEmpty())
    }
    @Test fun badFeedOrderingAndFutureTimeDoNotShowNotifications() {
        assertThrows(IllegalArgumentException::class.java){planHints(CoreHintFeed(feed,2,2,listOf(hint(2),hint(1))),HintCursor(feed,0),now)}
        assertThrows(IllegalArgumentException::class.java){planHints(CoreHintFeed("invalid",1,1,listOf(hint())),HintCursor(feed,0),now)}
        assertTrue(planHints(CoreHintFeed(feed,1,1,listOf(hint(at=now.plusSeconds(3600).toString()))),HintCursor(feed,0),now).show.isEmpty())
    }
    @Test fun explicitTargetAndStopAreEnforcedByController()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
        var row=rule();var calls=0
        val api=object:SuggestionsClient {
            override suspend fun list(offset:Int)=page(row)
            override suspend fun hints(afterId:Long)=emptyFeed()
            override suspend fun detail(id:String)=row
            override suspend fun refresh()=CoreStatus("ready")
            override suspend fun decide(id:String,decision:RuleDecision):CoreRule {
                calls++;row=row.copy(status="accepted",version=row.version+1,approvalValid=true,enabled=true,
                    action=CoreRuleAction(decision.target!!,"turn_on",buildJsonObject{}));return row
            }
        }
        try {
            val c=SuggestionsController(scope,{credentials("r1")},{"r1"},{api},100000)
            c.start();yield();c.decide(row,"accept","lock.private");yield();assertEquals(0,calls)
            c.decide(row,"accept","light.test");yield();assertEquals(1,calls)
            assertEquals("accepted",c.state.value.page!!.automations.first().status)
            c.close();c.decide(row,"disable");yield();assertEquals(1,calls)
            assertNull(c.state.value.page);assertNull(c.state.value.hints)
            assertFalse(c.state.value.toString().contains("private"))
        }finally{scope.cancel()}
    }
    @Test fun connectionChangedAfterDisplayCannotSendOldApprovalToNewCore()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
        var revision="old";var calls=0
        val api=object:SuggestionsClient {
            override suspend fun list(offset:Int)=page(rule())
            override suspend fun hints(afterId:Long)=emptyFeed()
            override suspend fun detail(id:String)=rule()
            override suspend fun refresh()=CoreStatus("ready")
            override suspend fun decide(id:String,decision:RuleDecision):CoreRule {calls++;return rule()}
        }
        try{
            val c=SuggestionsController(scope,{credentials(revision)},{revision},{api},100000)
            c.start();yield();revision="new";c.decide(rule(),"accept","light.test");yield()
            assertEquals(0,calls);assertTrue(c.state.value.message!!.contains("изменились"));c.close()
        }finally{scope.cancel()}
    }
    @Test fun decisionConflictRefreshesStateWithoutBlindRetryOrRawError()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
        var calls=0
        val api=object:SuggestionsClient {
            override suspend fun list(offset:Int)=page(rule())
            override suspend fun hints(afterId:Long)=emptyFeed()
            override suspend fun detail(id:String)=rule()
            override suspend fun refresh()=CoreStatus("ready")
            override suspend fun decide(id:String,decision:RuleDecision):CoreRule {calls++;throw HttpException(Response.error<CoreRule>(409,"private-body".toResponseBody()))}
        }
        try {
            val c=SuggestionsController(scope,{credentials("r1")},{"r1"},{api},100000)
            c.start();yield();c.decide(rule(),"accept","light.test");yield()
            assertEquals(1,calls);assertFalse(c.state.value.busy)
            assertFalse(c.state.value.message!!.contains("private"));assertTrue(c.state.value.message!!.contains("изменились"));c.close()
        }finally{scope.cancel()}
    }
    @Test fun lateResponseAfterStopDoesNotRestoreHintOrRulePayload()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
        val gate=CompletableDeferred<Unit>()
        val api=object:SuggestionsClient {
            override suspend fun list(offset:Int)=withContext(NonCancellable){gate.await();page(rule())}
            override suspend fun hints(afterId:Long)=emptyFeed()
            override suspend fun detail(id:String)=rule()
            override suspend fun refresh()=CoreStatus("ready")
            override suspend fun decide(id:String,decision:RuleDecision)=rule()
        }
        try{
            val c=SuggestionsController(scope,{credentials("r1")},{"r1"},{api},100000)
            c.start();c.close();gate.complete(Unit);yield()
            assertNull(c.state.value.page);assertNull(c.state.value.hints)
        }finally{gate.complete(Unit);scope.cancel()}
    }

    @Test fun hintAndDecisionRequestsUseProtectedLocalApiAndExactFields()=runBlocking {
        okhttp3.mockwebserver.MockWebServer().use {server->
            server.start()
            val json=kotlinx.serialization.json.Json {ignoreUnknownKeys=true}
            val key="task21-synthetic-test-key-0000000000"
            server.enqueue(okhttp3.mockwebserver.MockResponse().setBody("""{"feed_id":"$feed","latest_id":0,"next_id":0,"hints":[]}"""))
            server.enqueue(okhttp3.mockwebserver.MockResponse().setBody(json.encodeToString(CoreRule.serializer(),rule())))
            val api=ShadeApi.create(server.url("/").toString(),key)
            assertEquals(feed,api.hints().feedId)
            val get=server.takeRequest();assertEquals("/api/v1/hints?after_id=0&limit=20",get.path)
            assertEquals("Bearer $key",get.getHeader("Authorization"))
            api.decideAutomation(rule().id,RuleDecision("accept",1,"light.test"))
            val post=server.takeRequest();assertEquals("POST",post.method)
            assertEquals("Bearer $key",post.getHeader("Authorization"))
            val body=post.body.readUtf8()
            assertTrue(body.contains("\"target_entity\":\"light.test\""))
            assertFalse(body.contains(key));assertFalse(body.contains("params"))
        }
    }
}
