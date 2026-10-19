package com.shadeai.app

import android.os.Bundle
import android.content.Intent
import androidx.compose.runtime.LaunchedEffect
import com.shadeai.app.ui.CalendarRoute
import com.shadeai.app.ui.CalendarViewModel
import com.shadeai.app.ui.SuggestionsRoute
import com.shadeai.app.ui.SuggestionsViewModel
import com.shadeai.app.hints.HintDelivery
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
import com.shadeai.app.ui.CoreResultsRoute
import com.shadeai.app.ui.CoreResultsViewModel
import com.shadeai.app.ui.JournalViewModel

class MainActivity : ComponentActivity() {
    private var calendarNavigation by mutableStateOf(0)
    private var hintNavigation by mutableStateOf(0)
    private lateinit var sources: NotificationSourcesViewModel

    override fun onNewIntent(intent:Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if(intent.action==com.shadeai.app.reminders.ReminderDelivery.OPEN_ACTION){calendarNavigation++;intent.action=null}
        if(intent.action==HintDelivery.OPEN_ACTION){hintNavigation++;intent.action=null}
    }

    override fun onResume() {
        super.onResume()
        sources.refresh()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if(intent.action==com.shadeai.app.reminders.ReminderDelivery.OPEN_ACTION){calendarNavigation++;intent.action=null}
        if(intent.action==HintDelivery.OPEN_ACTION){hintNavigation++;intent.action=null}
        val light = resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK != Configuration.UI_MODE_NIGHT_YES
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = light
            isAppearanceLightNavigationBars = light
        }
        val model = ViewModelProvider(this)[ConnectionViewModel::class.java]
        sources = ViewModelProvider(this)[NotificationSourcesViewModel::class.java]
        val journal = ViewModelProvider(this)[JournalViewModel::class.java]
        val results = ViewModelProvider(this)[CoreResultsViewModel::class.java]
        val access = ViewModelProvider(this)[com.shadeai.app.ui.AccessViewModel::class.java]
        val voice = ViewModelProvider(this)[com.shadeai.app.ui.VoiceViewModel::class.java]
        val calendar = ViewModelProvider(this)[CalendarViewModel::class.java]
        val suggestions = ViewModelProvider(this)[SuggestionsViewModel::class.java]
        setContent {
            ShadeAITheme {
                val state by model.state.collectAsStateWithLifecycle()
                val sourcesState by sources.state.collectAsStateWithLifecycle()
                var screen by rememberSaveable { mutableStateOf("connection") }
                LaunchedEffect(calendarNavigation){if(calendarNavigation>0)screen="calendar"}
                LaunchedEffect(hintNavigation){if(hintNavigation>0)screen="suggestions"}
                BackHandler(screen != "connection") { screen = "connection" }
                when (screen) {
                    "access" -> com.shadeai.app.ui.AccessRoute(access){screen="connection"}
                    "voice" -> com.shadeai.app.ui.VoiceRoute(voice){screen="connection"}
                    "calendar" -> CalendarRoute(calendar){screen="connection"}
                    "suggestions" -> SuggestionsRoute(suggestions,{screen="connection"},{id->results.select(id);screen="results"})
                    "results" -> CoreResultsRoute(results) { screen = "connection" }
                    "sources" -> NotificationSourcesScreen(sourcesState, sources::toggle,
                        sources::refresh, { screen = "connection" })
                    "journal" -> JournalRoute(journal, { screen = "connection" },
                        { sources.refresh(); screen = "sources" })
                    else -> ConnectionScreen(state, model::editUrl, model::editKey,
                        model::saveAndCheck, model::clearKey, model::sendTest,
                        onSources = { sources.refresh(); screen = "sources" }, onJournal = { screen = "journal" },
                        onResults = { screen = "results" }, onSuggestions = {screen="suggestions"},onCalendar={screen="calendar"},onVoice={screen="voice"},onAccess={screen="access"})
                }
            }
        }
    }
}
