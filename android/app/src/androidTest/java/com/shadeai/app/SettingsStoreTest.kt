package com.shadeai.app

import android.content.Context
import android.content.ContextWrapper
import android.content.pm.ApplicationInfo
import android.security.NetworkSecurityPolicy
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.shadeai.app.core.config.ServerPrefs
import com.shadeai.app.core.config.SettingsStorageException
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SettingsStoreTest {
    private val target = InstrumentationRegistry.getInstrumentation().targetContext
    private val context = object : ContextWrapper(target) {
        override fun getSharedPreferences(name: String, mode: Int) = super.getSharedPreferences("task09_test_$name", mode)
    }
    private val key = "task09-instrumented-secret-0000000000"
    private val url = "http://127.0.0.1:8000/api/v1/"

    @Before fun reset() { context.getSharedPreferences("shade_prefs", Context.MODE_PRIVATE).edit().clear().commit() }
    @After fun cleanup() = reset()

    @Test fun encryptedKeyRoundTripAndDelete() {
        ServerPrefs.save(context, url, key)
        val loaded = ServerPrefs.load(context)
        assertEquals(url, loaded.baseUrl); assertEquals(key, loaded.apiKey)
        val values = context.getSharedPreferences("shade_prefs", Context.MODE_PRIVATE).all.values.joinToString()
        assertFalse(values.contains(key))
        assertFalse(loaded.toString().contains(key))
        ServerPrefs.clearKey(context)
        assertEquals("", ServerPrefs.load(context).apiKey)
        assertEquals(url, ServerPrefs.load(context).baseUrl)
    }

    @Test fun ciphertextCannotBeReassignedToAnotherHost() {
        ServerPrefs.save(context, url, key)
        context.getSharedPreferences("shade_prefs", Context.MODE_PRIVATE).edit()
            .putString("base_url", "http://localhost:8001/api/v1/").commit()
        try { ServerPrefs.load(context); fail("Перенос ключа должен отклоняться") }
        catch (error: SettingsStorageException) { assertFalse(error.toString().contains(key)) }
        ServerPrefs.clearKey(context)
        assertEquals("", ServerPrefs.load(context).apiKey)
    }

    @Test fun legacyAddressSurvivesWithoutKey() {
        context.getSharedPreferences("shade_prefs", Context.MODE_PRIVATE).edit().putString("base_url", url).commit()
        assertEquals(url, ServerPrefs.load(context).baseUrl)
        assertEquals("", ServerPrefs.load(context).apiKey)
    }

    @Test fun platformTransportAndBackupPolicy() {
        val policy = NetworkSecurityPolicy.getInstance()
        assertTrue(policy.isCleartextTrafficPermitted("127.0.0.1"))
        assertFalse(policy.isCleartextTrafficPermitted("127.0.0.2"))
        assertFalse(policy.isCleartextTrafficPermitted("example.com"))
        assertEquals(0, target.applicationInfo.flags and ApplicationInfo.FLAG_ALLOW_BACKUP)
    }
}
