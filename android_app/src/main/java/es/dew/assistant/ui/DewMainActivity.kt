package es.dew.assistant.ui

import android.content.ComponentCallbacks2
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.ui.graphics.Color
import es.dew.assistant.core.DewHardwareProfiler
import es.dew.assistant.core.DewNativeBridge

private val OrcaDarkColorScheme = darkColorScheme(
    primary = Color(0xFF10B981),          // Emerald Orca Accent
    onPrimary = Color(0xFF042F2E),
    primaryContainer = Color(0xFF064E3B),
    onPrimaryContainer = Color(0xFFA7F3D0),
    secondary = Color(0xFF38BDF8),        // Cyan Terminal Accent
    onSecondary = Color(0xFF082F49),
    secondaryContainer = Color(0xFF0C4A6E),
    onSecondaryContainer = Color(0xFFE0F2FE),
    tertiary = Color(0xFFF59E0B),         // Amber <think> Accent
    background = Color(0xFF090D16),       // Deep Obsidian Background
    onBackground = Color(0xFFF1F5F9),
    surface = Color(0xFF111827),          // Dark Slate Card Surface
    onSurface = Color(0xFFF8FAFC),
    surfaceVariant = Color(0xFF1E293B),
    onSurfaceVariant = Color(0xFF94A3B8),
    error = Color(0xFFEF4444),
    errorContainer = Color(0xFF450A0A),
    onErrorContainer = Color(0xFFFECACA)
)

class DewMainActivity : ComponentActivity() {

    private lateinit var viewModel: DewViewModel

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val ramGb = DewHardwareProfiler.getTotalDeviceRamGb(this)
        viewModel = DewViewModel(deviceRamGb = ramGb)

        setContent {
            MaterialTheme(colorScheme = OrcaDarkColorScheme) {
                DewMainScreen(viewModel = viewModel)
            }
        }
    }

    override fun onTrimMemory(level: Int) {
        super.onTrimMemory(level)
        val isGenuineMemoryPressure =
            (level >= ComponentCallbacks2.TRIM_MEMORY_RUNNING_LOW &&
                level != ComponentCallbacks2.TRIM_MEMORY_UI_HIDDEN) ||
                level >= ComponentCallbacks2.TRIM_MEMORY_BACKGROUND
        if (isGenuineMemoryPressure && DewNativeBridge.isNativeLoaded()) {
            DewNativeBridge.nativeOnTrimMemoryPressure()
        }
    }
}
