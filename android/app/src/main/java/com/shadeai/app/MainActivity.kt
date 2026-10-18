package com.shadeai.app

import android.os.Bundle
import android.content.res.Configuration
import androidx.core.view.WindowCompat
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.activity.compose.BackHandler
import com.shadeai.app.ui.NotificationSourcesScreen
import com.shadeai.app.ui.NotificationSourcesViewModel
import com.shadeai.app.ui.ConnectionScreen
import com.shadeai.app.ui.ConnectionViewModel
import com.shadeai.app.ui.theme.ShadeAITheme
import com.shadeai.app.ui.JournalRoute
import com.shadeai.app.ui.JournalViewModel

class MainActivity : ComponentActivity() {
    private lateinit var sources: NotificationSourcesViewModel

    override fun onResume() {
        super.onResume()
        sources.refresh()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val light = resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK != Configuration.UI_MODE_NIGHT_YES
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = light
            isAppearanceLightNavigationBars = light
        }
        val model = ViewModelProvider(this)[ConnectionViewModel::class.java]
        sources = ViewModelProvider(this)[NotificationSourcesViewModel::class.java]
        val journal = ViewModelProvider(this)[JournalViewModel::class.java]
        setContent {
            ShadeAITheme {
                val state by model.state.collectAsStateWithLifecycle()
                val sourcesState by sources.state.collectAsStateWithLifecycle()
                var screen by rememberSaveable { mutableStateOf("connection") }
                BackHandler(screen != "connection") { screen = "connection" }
                when (screen) {
                    "sources" -> NotificationSourcesScreen(sourcesState, sources::toggle,
                        sources::refresh, { screen = "connection" })
                    "journal" -> JournalRoute(journal, { screen = "connection" },
                        { sources.refresh(); screen = "sources" })
                    else -> ConnectionScreen(state, model::editUrl, model::editKey,
                        model::saveAndCheck, model::clearKey, model::sendTest,
                        onSources = { sources.refresh(); screen = "sources" }, onJournal = { screen = "journal" })
                }
            }
        }
    }
}
