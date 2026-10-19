package com.shadeai.app

import com.shadeai.app.core.network.*
import com.shadeai.app.ui.*
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response

class CalendarTest {
    private fun event()=CoreCalendarEvent("cal_"+"a".repeat(32),"private-synthetic-calendar",null,
        "2026-10-19T05:00:00Z","2026-10-19T06:00:00Z",null,null,false,"confirmed",true,1,"2026-10-19T03:00:00Z")
    private fun page(total:Int=1)=CoreCalendarPage("ready",true,false,"Asia/Yekaterinburg",null,listOf(event()),total)
    private fun saved(revision:String)=ResultsCredentials(revision,"http://127.0.0.1:8000/","synthetic-test-key")
    @Test fun supportedDatesTimezoneAndStatusAreSafe(){
        val row=event();assertTrue(knownCalendar(page()))
        assertTrue(calendarTime(row,"Asia/Yekaterinburg").contains("10:00"))
        val all=row.copy(allDay=true,startDate="2026-10-19",endDate="2026-10-20")
        assertTrue(calendarTime(all,"America/Los_Angeles").contains("19 октября"))
        assertFalse(knownCalendar(page().copy(events=listOf(row.copy(status="future-private")))))
        assertFalse(knownCalendar(page().copy(events=listOf(all.copy(endDate="invalid")))))
        assertFalse(knownCalendar(page().copy(timezone="Invalid/Private")))
        assertFalse(page().toString().contains("private"))
    }
    @Test fun inactiveConnectionChangeResetsOffsetAndFilterBeforeNewServerRead()=runBlocking{
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);var revision="old"
        val seen=mutableListOf<Triple<String,Int,Boolean>>()
        val c=CalendarController(scope,{saved(revision)},{revision},{connection->object:CalendarClient{
            override suspend fun page(offset:Int,inactive:Boolean):CoreCalendarPage{seen.add(Triple(connection.revision,offset,inactive));return page(100)}
            override suspend fun sync()=CoreStatus("ready")
        }},100000)
        try{
            c.start();yield();c.filter(true);yield();c.next();yield();assertEquals(50,c.state.value.offset)
            c.close();assertNull(c.state.value.page);revision="new";c.start();yield()
            assertEquals(Triple("new",0,false),seen.last());assertEquals(0,c.state.value.offset)
        }finally{c.close();scope.cancel()}
    }
    @Test fun responseAfterStopCannotRestorePayload()=runBlocking{
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val pending=CompletableDeferred<CoreCalendarPage>()
        val c=CalendarController(scope,{saved("same")},{"same"},{object:CalendarClient{
            override suspend fun page(offset:Int,inactive:Boolean)=withContext(NonCancellable){pending.await()}
            override suspend fun sync()=CoreStatus("ready")
        }},100000)
        try{c.start();yield();c.close();pending.complete(page());yield();assertNull(c.state.value.page)
        }finally{pending.complete(page());scope.cancel()}
    }
    @Test fun explicitSyncIsPinnedToDisplayedConnection()=runBlocking{
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);var revision="old";var calls=0
        val c=CalendarController(scope,{saved(revision)},{revision},{object:CalendarClient{
            override suspend fun page(offset:Int,inactive:Boolean)=page()
            override suspend fun sync():CoreStatus{calls++;return CoreStatus("ready")}
        }},100000)
        try{c.start();yield();revision="new";c.sync();yield();assertEquals(0,calls);assertTrue(c.state.value.message!!.contains("изменились"))
            c.sync();yield();assertEquals(1,calls)
        }finally{c.close();scope.cancel()}
    }
    @Test fun authFailureClearsDataWithoutRawErrorBody()=runBlocking{
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);var denied=false
        val c=CalendarController(scope,{saved("same")},{"same"},{object:CalendarClient{
            override suspend fun page(offset:Int,inactive:Boolean):CoreCalendarPage{if(denied)throw HttpException(Response.error<CoreCalendarPage>(401,"private-error".toResponseBody()));return page()}
            override suspend fun sync()=CoreStatus("ready")
        }},100000)
        try{c.start();yield();assertNotNull(c.state.value.page);denied=true;c.refresh();yield();assertNull(c.state.value.page);assertFalse(c.state.value.error!!.contains("private"))
        }finally{c.close();scope.cancel()}
    }
    @Test fun actualRetrofitCalendarUsesBearerAndExactQuery()=runBlocking{
        val server=MockWebServer();server.start()
        try{
            server.enqueue(MockResponse().setBody("""{"status":"ready","configured":true,"stale":false,"timezone":"UTC","events":[],"total":0}"""))
            server.enqueue(MockResponse().setBody("""{"status":"ready"}"""))
            val api=ShadeApi.create(server.url("/").toString(),"synthetic-calendar-test-key-000000001")
            assertTrue(knownCalendar(api.calendar(50,true)));assertEquals("ready",api.syncCalendar().status)
            val first=server.takeRequest();assertEquals("Bearer synthetic-calendar-test-key-000000001",first.getHeader("Authorization"))
            assertEquals("/api/v1/calendar/events?offset=50&include_inactive=true&limit=50",first.path)
            val second=server.takeRequest();assertEquals("POST",second.method);assertEquals("/api/v1/calendar/sync",second.path)
            assertFalse(second.body.readUtf8().contains("synthetic-calendar-test-key-000000001"))
        }finally{server.shutdown()}
    }
}
