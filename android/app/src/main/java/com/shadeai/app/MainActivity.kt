package com.shadeai.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.compose.runtime.getValue
import com.shadeai.app.ui.ConnectionScreen
import com.shadeai.app.ui.ConnectionViewModel
import com.shadeai.app.ui.theme.ShadeAITheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val model = ViewModelProvider(this)[ConnectionViewModel::class.java]
        setContent {
            ShadeAITheme {
                val state by model.state.collectAsStateWithLifecycle()
                ConnectionScreen(state, model::editUrl, model::editKey,
                    model::saveAndCheck, model::clearKey, model::sendTest)
            }
        }
    }
}
