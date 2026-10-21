package com.mixnavuts.app.ui

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.mixnavuts.app.NavigationController
import com.mixnavuts.app.navigation

class MainActivity : ComponentActivity() {
    private val permissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val controller = navigation
        controller.loadPlaces()
        setContent {
            // Placeholder theme: the visual design is applied here later.
            MaterialTheme {
                Surface {
                    AppRoot(controller, requestLocation = ::requestLocation)
                }
            }
        }
    }

    private fun requestLocation() {
        val wanted = mutableListOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) wanted += Manifest.permission.POST_NOTIFICATIONS
        permissions.launch(wanted.toTypedArray())
    }
}

@Composable
fun AppRoot(controller: NavigationController, requestLocation: () -> Unit) {
    val state by controller.state.collectAsStateWithLifecycle()
    if (state.navigating) {
        GuidanceScreen(state, onStop = controller::stop)
    } else {
        PlanScreen(state, controller, requestLocation)
    }
}
