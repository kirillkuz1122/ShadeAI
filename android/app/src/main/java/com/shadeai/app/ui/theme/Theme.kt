package com.shadeai.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

private val DarkColors = darkColorScheme(
    primary = OrangeWarmth,
    secondary = ScarletFire,
    background = CharcoalBrown,
    surface = CharcoalBrown,
    onPrimary = CharcoalBrown,
    onSecondary = CreamLight,
    onBackground = CreamLight,
    onSurface = CreamLight,
    surfaceVariant = CharcoalBrown,
    onSurfaceVariant = CreamLight,
    outline = CreamLight.copy(alpha = 0.4f),
    error = ScarletFire,
    onError = CreamLight,
)

private val LightColors = lightColorScheme(
    primary = OrangeWarmth,
    secondary = ScarletFire,
    background = CreamLight,
    surface = CreamLight,
    onPrimary = CharcoalBrown,
    onSecondary = CharcoalBrown,
    onBackground = CharcoalBrown,
    onSurface = CharcoalBrown,
    surfaceVariant = CreamLight,
    onSurfaceVariant = CharcoalBrown,
    outline = CharcoalBrown.copy(alpha = 0.4f),
    error = ScarletFire,
    onError = CreamLight,
)

@Composable
fun ShadeAITheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) DarkColors else LightColors,
        content = content,
    )
}
