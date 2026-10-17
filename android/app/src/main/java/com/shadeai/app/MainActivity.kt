package com.shadeai.app

import android.os.Bundle
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

class MainActivity : ComponentActivity() {
    private lateinit var sources: NotificationSourcesViewModel

    override fun onResume() {
        super.onResume()
        sources.refresh()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val model = ViewModelProvider(this)[ConnectionViewModel::class.java]
        sources = ViewModelProvider(this)[NotificationSourcesViewModel::class.java]
        setContent {
            ShadeAITheme {
                val state by model.state.collectAsStateWithLifecycle()
                val sourcesState by sources.state.collectAsStateWithLifecycle()
                var showSources by rememberSaveable { mutableStateOf(false) }
                BackHandler(showSources) { showSources = false }
                if (showSources) NotificationSourcesScreen(sourcesState, sources::toggle,
                    sources::refresh, { showSources = false })
                else ConnectionScreen(state, model::editUrl, model::editKey,
                    model::saveAndCheck, model::clearKey, model::sendTest,
                    onSources = { sources.refresh(); showSources = true })
            }
        }
    }
}
