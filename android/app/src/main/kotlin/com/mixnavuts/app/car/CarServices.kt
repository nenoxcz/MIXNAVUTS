package com.mixnavuts.app.car

import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Rect
import android.view.Surface
import androidx.car.app.AppManager
import androidx.car.app.CarContext
import androidx.car.app.SurfaceCallback
import androidx.car.app.SurfaceContainer
import androidx.car.app.hardware.CarHardwareManager
import androidx.car.app.hardware.common.CarValue
import androidx.car.app.hardware.common.OnCarDataAvailableListener
import androidx.car.app.hardware.info.CarInfo
import androidx.car.app.hardware.info.Speed
import androidx.car.app.navigation.NavigationManager
import androidx.car.app.navigation.NavigationManagerCallback
import androidx.car.app.versioning.CarAppApiLevels
import androidx.core.content.ContextCompat
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.coroutineScope
import androidx.lifecycle.repeatOnLifecycle
import com.mixnavuts.app.NavState
import com.mixnavuts.app.NavigationController
import com.mixnavuts.core.ScreenFit
import kotlinx.coroutines.launch

/**
 * Tells the car we are navigating and keeps the cluster/HUD fed with
 * NavigationManager.updateTrip. Also handles the host's stop and auto-drive.
 */
class CarNavigationBridge(
    carContext: CarContext,
    private val controller: NavigationController,
    lifecycle: Lifecycle,
) : DefaultLifecycleObserver {
    private val manager = carContext.getCarService(NavigationManager::class.java)
    private var started = false

    init {
        manager.setNavigationManagerCallback(object : NavigationManagerCallback {
            override fun onStopNavigation() {
                controller.stop()
            }

            override fun onAutoDriveEnabled() {
                controller.restartWithSimulation()
            }
        })
        lifecycle.addObserver(this)
        lifecycle.coroutineScope.launch {
            lifecycle.repeatOnLifecycle(Lifecycle.State.CREATED) {
                controller.state.collect { onState(it) }
            }
        }
    }

    private fun onState(state: NavState) {
        if (state.navigating && !started) {
            manager.navigationStarted()
            started = true
        } else if (!state.navigating && started) {
            manager.navigationEnded()
            started = false
        }
        val update = state.navigation
        if (started && update != null) manager.updateTrip(CarTemplates.trip(update, state.destinationName))
    }

    override fun onDestroy(owner: LifecycleOwner) {
        if (started) manager.navigationEnded()
        started = false
        manager.clearNavigationManagerCallback()
    }
}

/**
 * Draws the route on the Android Auto map surface. Placeholder rendering:
 * a map SDK that can render into a Surface can replace it later.
 */
class RouteSurfaceRenderer(
    carContext: CarContext,
    private val controller: NavigationController,
    lifecycle: Lifecycle,
) : SurfaceCallback {
    private var surface: Surface? = null
    private var width = 0
    private var height = 0
    private var visibleArea: Rect? = null

    private val routePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(0x1E, 0x88, 0xE5)
        style = Paint.Style.STROKE
        strokeWidth = 12f
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val carPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE }

    init {
        carContext.getCarService(AppManager::class.java).setSurfaceCallback(this)
        lifecycle.coroutineScope.launch {
            lifecycle.repeatOnLifecycle(Lifecycle.State.CREATED) {
                controller.state.collect { render(it) }
            }
        }
    }

    override fun onSurfaceAvailable(surfaceContainer: SurfaceContainer) {
        surface = surfaceContainer.surface
        width = surfaceContainer.width
        height = surfaceContainer.height
        render(controller.state.value)
    }

    override fun onVisibleAreaChanged(visibleArea: Rect) {
        this.visibleArea = visibleArea
        render(controller.state.value)
    }

    override fun onStableAreaChanged(stableArea: Rect) = Unit

    override fun onSurfaceDestroyed(surfaceContainer: SurfaceContainer) {
        surface = null
    }

    private fun render(state: NavState) {
        val target = surface ?: return
        if (!target.isValid) return
        val canvas = target.lockCanvas(null)
        try {
            canvas.drawColor(Color.rgb(0x16, 0x16, 0x16))
            val update = state.navigation
            val route = update?.route ?: state.selectedRoute ?: return
            // While driving, show the stretch around the car; otherwise the whole route.
            val shown = update?.let { u ->
                route.points.filter { it.distanceM in (u.progress.alongM - 400)..(u.progress.alongM + 1_600) }
            }?.takeIf { it.size >= 2 } ?: route.points
            if (shown.size < 2) return
            val area = visibleArea ?: Rect(0, 0, width, height)
            val fit = ScreenFit(shown, area.width().toFloat(), area.height().toFloat(), 48f)
            val path = Path()
            route.points.forEachIndexed { i, p ->
                val x = area.left + fit.x(p.lat, p.lon)
                val y = area.top + fit.y(p.lat, p.lon)
                if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
            }
            canvas.drawPath(path, routePaint)
            update?.let {
                canvas.drawCircle(
                    area.left + fit.x(it.progress.snappedLat, it.progress.snappedLon),
                    area.top + fit.y(it.progress.snappedLat, it.progress.snappedLon),
                    16f,
                    carPaint,
                )
            }
        } finally {
            target.unlockCanvasAndPost(canvas)
        }
    }
}

/** Vehicle speed from the car (Car App API level 3+); the HUD prefers it over GNSS speed. */
class VehicleSpeedReader(
    private val carContext: CarContext,
    private val controller: NavigationController,
    lifecycle: Lifecycle,
) : DefaultLifecycleObserver {
    private val listener = OnCarDataAvailableListener<Speed> { speed ->
        val value = speed.rawSpeedMetersPerSecond
        controller.setVehicleSpeed(if (value.status == CarValue.STATUS_SUCCESS) value.value?.toDouble() else null)
    }
    private val carInfo: CarInfo? =
        if (carContext.carAppApiLevel >= CarAppApiLevels.LEVEL_3) {
            runCatching { carContext.getCarService(CarHardwareManager::class.java).carInfo }.getOrNull()
        } else {
            null
        }

    init {
        lifecycle.addObserver(this)
    }

    override fun onCreate(owner: LifecycleOwner) {
        runCatching { carInfo?.addSpeedListener(ContextCompat.getMainExecutor(carContext), listener) }
    }

    override fun onDestroy(owner: LifecycleOwner) {
        runCatching { carInfo?.removeSpeedListener(listener) }
        controller.setVehicleSpeed(null)
    }
}
