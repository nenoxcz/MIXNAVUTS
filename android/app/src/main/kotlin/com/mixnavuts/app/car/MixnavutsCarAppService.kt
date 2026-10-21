package com.mixnavuts.app.car

import android.content.Intent
import android.content.pm.ApplicationInfo
import androidx.car.app.CarAppService
import androidx.car.app.Screen
import androidx.car.app.Session
import androidx.car.app.SessionInfo
import androidx.car.app.validation.HostValidator
import com.mixnavuts.app.navigation

/**
 * Android Auto entry point. The main display gets the full navigation session;
 * the instrument cluster (계기판) gets a guidance-only session.
 */
class MixnavutsCarAppService : CarAppService() {
    override fun createHostValidator(): HostValidator =
        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0) {
            HostValidator.ALLOW_ALL_HOSTS_VALIDATOR
        } else {
            HostValidator.Builder(applicationContext)
                .addAllowedHosts(androidx.car.app.R.array.hosts_allowlist_sample)
                .build()
        }

    override fun onCreateSession(sessionInfo: SessionInfo): Session =
        if (sessionInfo.displayType == SessionInfo.DISPLAY_TYPE_CLUSTER) ClusterSession() else MainCarSession()
}

class MainCarSession : Session() {
    override fun onCreateScreen(intent: Intent): Screen {
        val controller = carContext.navigation
        controller.loadPlaces()
        CarNavigationBridge(carContext, controller, lifecycle)
        RouteSurfaceRenderer(carContext, controller, lifecycle)
        VehicleSpeedReader(carContext, controller, lifecycle)
        return if (controller.state.value.navigating) {
            GuidanceCarScreen(carContext, controller)
        } else {
            DestinationScreen(carContext, controller)
        }
    }
}

class ClusterSession : Session() {
    override fun onCreateScreen(intent: Intent): Screen = GuidanceCarScreen(carContext, carContext.navigation, cluster = true)
}
