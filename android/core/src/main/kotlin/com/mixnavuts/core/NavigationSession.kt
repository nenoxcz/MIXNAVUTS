package com.mixnavuts.core

import java.time.ZoneId

interface RoutesApi {
    suspend fun routes(request: RouteRequest): RoutesResponse
}

data class NavUpdate(
    val route: RouteOption,
    val progress: Progress,
    val hud: HudState,
    val fix: Fix,
    val rerouted: Boolean,
    val rerouteError: String?,
)

/**
 * One guided trip: feeds fixes to the tracker, asks the engine for a new
 * route when the driver leaves the current one, and builds the HUD state.
 * Call `onFix` from a single coroutine.
 */
class NavigationSession(
    private val api: RoutesApi,
    route: RouteOption,
    private val destination: Endpoint,
    private val mode: String,
    private val zone: ZoneId = ZoneId.systemDefault(),
    private val rerouteCooldownS: Double = 15.0,
) {
    var route: RouteOption = route
        private set
    var vehicleSpeedMps: Double? = null

    private var tracker = RouteTracker(route)
    private var lastRerouteAt = Double.NEGATIVE_INFINITY

    suspend fun onFix(fix: Fix): NavUpdate {
        var progress = tracker.update(fix)
        var rerouted = false
        var error: String? = null
        if (progress.state == GuidanceState.OFF_ROUTE && fix.time - lastRerouteAt >= rerouteCooldownS) {
            lastRerouteAt = fix.time
            try {
                val response = api.routes(RouteRequest(Endpoint.at(fix.lat, fix.lon), destination, fix.time, mode, k = 1))
                response.routes.firstOrNull()?.let {
                    route = it
                    tracker = RouteTracker(it)
                    progress = tracker.update(fix)
                    rerouted = true
                }
            } catch (e: Exception) {
                error = e.message ?: e.javaClass.simpleName
            }
        }
        return NavUpdate(route, progress, Hud.build(progress, fix, vehicleSpeedMps, zone), fix, rerouted, error)
    }
}
