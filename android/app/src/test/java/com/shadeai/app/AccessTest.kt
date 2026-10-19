package com.shadeai.app

import com.shadeai.app.core.network.*
import com.shadeai.app.ui.*
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant
import java.util.UUID

class AccessTest {
    private val hash = "a".repeat(64)
    private val now = Instant.now()
    private fun grant() = CoreAccessGrant(UUID.randomUUID().toString(), 42, "lock.test", hash, 2,
        "active", stateObserved=false, createdAt=now.toString(), expiresAt=now.plusSeconds(120).toString(),
        updatedAt=now.toString())
    private fun page() = CoreAccess(1, true, "shade_keypad", hash, listOf("lock.test"), 15, true, true, listOf(grant()))

    @Test fun pinIsAcceptedOnlyInOneTimeIssuanceResponseAndNeverHistory() {
        val secret = grant().copy(pin="012345")
        assertTrue(knownAccessGrant(secret, allowPin=true))
        assertFalse(knownAccessGrant(secret))
        assertFalse(knownAccess(page().copy(grants=listOf(secret))))
        assertFalse(secret.toString().contains("012345"))
        assertFalse(knownAccessGrant(secret.copy(state="used"), allowPin=true))
        assertFalse(knownAccessGrant(secret.copy(pin="private"), allowPin=true))
        assertTrue(knownAccess(page()))
    }

    @Test fun incompatibleTargetsPoliciesAndWindowsAreRejected() {
        assertFalse(knownAccess(page().copy(adapter="vendor_cloud")))
        assertFalse(knownAccess(page().copy(oneUse=false)))
        assertFalse(knownAccess(page().copy(ownerConfirmation=false)))
        assertFalse(knownAccess(page().copy(allowedLocks=listOf("light.test"))))
        assertFalse(knownAccessGrant(grant().copy(durationMinutes=16)))
        assertFalse(knownAccessGrant(grant().copy(expiresAt=now.plusSeconds(121).toString())))
        assertFalse(knownAccessGrant(grant().copy(state="future-state")))
    }

    @Test fun consentAndManualCheckAreMandatorySerializedBooleans() {
        val body = Json.encodeToString(AccessCreation(42,"lock.test",2,hash,true,true))
        assertTrue(body.contains("\"confirmed\":true"))
        assertTrue(body.contains("\"delivery_checked\":true"))
        assertEquals("{\"checked\":true}",Json.encodeToString(AccessRevocation(true)))
        assertEquals("{\"checked\":false}",Json.encodeToString(AccessRevocation(false)))
    }

    @Test fun actualRetrofitUsesOwnerBearerAndSeparateStateRevokeRoutes() = runBlocking {
        val server=MockWebServer();server.start()
        try {
            val row=grant().copy(pin="012345")
            server.enqueue(MockResponse().setBody(Json.encodeToString(page())))
            server.enqueue(MockResponse().setBody(Json.encodeToString(row)))
            server.enqueue(MockResponse().setBody(Json.encodeToString(row.copy(pin=null))))
            server.enqueue(MockResponse().setBody(Json.encodeToString(row.copy(pin=null,state="revoked"))))
            val api=ShadeApi.create(server.url("/api/v1/").toString(),"synthetic-access-owner-key-000000001")
            assertTrue(knownAccess(api.access()))
            assertEquals("012345",api.createAccess(AccessCreation(42,"lock.test",2,hash,true,true)).pin)
            assertNull(api.accessState(row.id).pin)
            assertEquals("revoked",api.revokeAccess(row.id,AccessRevocation(true)).state)
            val requests=(1..4).map{server.takeRequest()}
            assertTrue(requests.all{it.getHeader("Authorization")=="Bearer synthetic-access-owner-key-000000001"})
            assertEquals("/api/v1/access/grants/${row.id}/revoke",requests[3].path)
            assertEquals("{\"checked\":true}",requests[3].body.readUtf8())
            assertTrue(requests[1].body.readUtf8().contains("\"delivery_checked\":true"))
            assertTrue(requests.none{it.path!!.contains("012345")})
        } finally {server.shutdown()}
    }
}
