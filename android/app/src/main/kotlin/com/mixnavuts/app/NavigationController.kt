package com.mixnavuts.app

import android.content.Context
import com.mixnavuts.app.location.DeviceLocation
import com.mixnavuts.app.service.NavigationService
import com.mixnavuts.core.Endpoint
import com.mixnavuts.core.Fix
import com.mixnavuts.core.MixnavutsApi
import com.mixnavuts.core.NavUpdate
import com.mixnavuts.core.NavigationSession
import com.mixnavuts.core.Place
import com.mixnavuts.core.RouteOption
import com.mixnavuts.core.RouteRequest
import com.mixnavuts.core.RouteSimulator
import com.mixnavuts.core.RoutesResponse
import com.mixnavuts.core.toEndpoint
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class NavState(
    val places: List<Place> = emptyList(),
    val synthetic: Boolean = true,
    val origin: Place? = null,
    val originIsCurrentLocation: Boolean = false,
    val destination: Place? = null,
    val searchResults: List<Place> = emptyList(),
    val mode: String = "balanced",
    val plan: RoutesResponse? = null,
    val selectedIndex: Int = 0,
    val loading: Boolean = false,
    val error: String? = null,
    val simulate: Boolean = true,
    val simulationSpeed: Double = 1.0,
    val navigating: Boolean = false,
    val navigation: NavUpdate? = null,
    val vehicleSpeedMps: Double? = null,
) {
    val selectedRoute: RouteOption? get() = plan?.routes?.getOrNull(selectedIndex)
    val destinationName: String get() = destination?.name.orEmpty()
}

/**
 * App state and actions. Screens (phone, Android Auto, cluster) observe `state`
 * and call these methods; none of them talk to the engine directly.
 */
class NavigationController(private val context: Context, private val api: MixnavutsApi) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val _state = MutableStateFlow(NavState())
    val state: StateFlow<NavState> = _state.asStateFlow()

    val location = DeviceLocation(context)
    private var session: NavigationSession? = null
    private var driveJob: Job? = null

    fun loadPlaces() = launch {
        if (_state.value.places.isNotEmpty()) return@launch
        val response = api.places()
        _state.update { s ->
            s.copy(
                places = response.places,
                synthetic = response.synthetic,
                origin = s.origin ?: response.places.firstOrNull().takeIf { response.synthetic },
                originIsCurrentLocation = s.originIsCurrentLocation || !response.synthetic,
                error = null,
            )
        }
    }

    fun setOrigin(place: Place) = _state.update { it.copy(origin = place, originIsCurrentLocation = false, plan = null) }

    fun useCurrentLocationAsOrigin() = _state.update { it.copy(originIsCurrentLocation = true, plan = null) }

    fun setDestination(place: Place) = _state.update { it.copy(destination = place, plan = null, searchResults = emptyList()) }

    fun setMode(mode: String) = _state.update { it.copy(mode = mode, plan = null) }

    fun setSimulate(simulate: Boolean) = _state.update { it.copy(simulate = simulate) }

    fun setSimulationSpeed(speed: Double) = _state.update { it.copy(simulationSpeed = speed) }

    fun selectRoute(index: Int) = _state.update { it.copy(selectedIndex = index) }

    fun clearError() = _state.update { it.copy(error = null) }

    fun search(query: String) = launch {
        val near = location.lastKnown()?.let { it.lat to it.lon }
        val response = api.search(query, near)
        _state.update { it.copy(searchResults = response.results, error = if (response.results.isEmpty()) "검색 결과가 없습니다" else null) }
    }

    fun plan() = launch {
        val s = _state.value
        val destination = s.destination ?: error("목적지를 선택하세요")
        val origin = if (s.originIsCurrentLocation) {
            location.lastKnown()?.let { Endpoint.at(it.lat, it.lon) } ?: error("현재 위치를 아직 모릅니다")
        } else {
            s.origin?.toEndpoint() ?: error("출발지를 선택하세요")
        }
        _state.update { it.copy(loading = true, error = null, plan = null) }
        val response = api.routes(RouteRequest(origin, destination.toEndpoint(), System.currentTimeMillis() / 1000.0, s.mode, k = 4))
        _state.update { it.copy(loading = false, plan = response, selectedIndex = 0) }
    }

    fun start(index: Int = _state.value.selectedIndex) {
        val s = _state.value
        val route = s.plan?.routes?.getOrNull(index) ?: return
        val destination = s.destination ?: return
        stopDriving()
        val nav = NavigationSession(api, route, destination.toEndpoint(), s.mode).also { it.vehicleSpeedMps = s.vehicleSpeedMps }
        session = nav
        _state.update { it.copy(navigating = true, selectedIndex = index, navigation = null, error = null) }
        val fixes = if (s.simulate) simulatedFixes(route, s.simulationSpeed) else location.fixes()
        driveJob = scope.launch {
            try {
                fixes.collect { fix -> _state.update { it.copy(navigation = nav.onFix(fix)) } }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(error = e.message ?: e.toString()) }
            }
        }
        if (!s.simulate) NavigationService.start(context)
    }

    /** Android Auto's "auto drive" (DHU) and the phone's simulation switch both land here. */
    fun restartWithSimulation() {
        setSimulate(true)
        if (_state.value.navigating) start()
    }

    fun stop() {
        stopDriving()
        _state.update { it.copy(navigating = false, navigation = null) }
    }

    fun setVehicleSpeed(mps: Double?) {
        session?.vehicleSpeedMps = mps
        _state.update { it.copy(vehicleSpeedMps = mps) }
    }

    private fun stopDriving() {
        driveJob?.cancel()
        driveJob = null
        session = null
        NavigationService.stop(context)
    }

    private fun simulatedFixes(route: RouteOption, speed: Double): Flow<Fix> = flow {
        val simulator = RouteSimulator(route, System.currentTimeMillis() / 1000.0)
        var t = 0.0
        while (t < simulator.durationS) {
            emit(simulator.fixAt(t))
            delay(1_000L)
            t += speed
        }
        emit(simulator.fixAt(simulator.durationS))
    }

    private fun launch(block: suspend () -> Unit) = scope.launch {
        try {
            block()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _state.update { it.copy(loading = false, error = e.message ?: e.toString()) }
        }
    }
}
