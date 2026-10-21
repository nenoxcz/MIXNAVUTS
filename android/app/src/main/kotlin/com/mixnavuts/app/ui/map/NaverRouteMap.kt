package com.mixnavuts.app.ui.map

import android.content.Context
import android.graphics.Color
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.mixnavuts.core.RouteOption
import com.naver.maps.geometry.LatLng
import com.naver.maps.geometry.LatLngBounds
import com.naver.maps.map.CameraUpdate
import com.naver.maps.map.MapView
import com.naver.maps.map.NaverMap
import com.naver.maps.map.NaverMapSdk
import com.naver.maps.map.overlay.PathOverlay

/**
 * 네이버 지도 SDK setup. The client ID comes from 네이버 클라우드 플랫폼
 * (Maps · Mobile Dynamic Map); set `naver.map.clientId` in android/local.properties.
 *
 * Newer SDK releases moved to NCP "key ID" authentication
 * (`NaverMapSdk.NcpKeyClient`); switch the client here when upgrading the SDK.
 */
object NaverMapSetup {
    var enabled = false
        private set

    fun init(context: Context, clientId: String) {
        if (clientId.isBlank()) return
        NaverMapSdk.getInstance(context).client = NaverMapSdk.NaverCloudPlatformClient(clientId)
        enabled = true
    }
}

@Composable
fun NaverRouteMap(
    route: RouteOption?,
    position: Pair<Double, Double>?,
    bearing: Float?,
    follow: Boolean,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val mapView = remember { MapView(context) }
    val path = remember { PathOverlay() }
    var naverMap by remember { mutableStateOf<NaverMap?>(null) }

    DisposableEffect(lifecycle, mapView) {
        mapView.onCreate(null)
        mapView.getMapAsync { naverMap = it }
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> mapView.onStart()
                Lifecycle.Event.ON_RESUME -> mapView.onResume()
                Lifecycle.Event.ON_PAUSE -> mapView.onPause()
                Lifecycle.Event.ON_STOP -> mapView.onStop()
                else -> Unit
            }
        }
        lifecycle.addObserver(observer)
        onDispose {
            lifecycle.removeObserver(observer)
            if (lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) mapView.onPause()
            if (lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) mapView.onStop()
            mapView.onDestroy()
        }
    }

    AndroidView(factory = { mapView }, modifier = modifier)

    LaunchedEffect(naverMap, route?.id) {
        val map = naverMap ?: return@LaunchedEffect
        val coords = route?.points?.map { LatLng(it.lat, it.lon) }.orEmpty()
        if (coords.size < 2) {
            path.map = null
            return@LaunchedEffect
        }
        path.coords = coords
        path.width = 18
        path.outlineWidth = 3
        path.color = Color.rgb(0x1E, 0x88, 0xE5)
        path.map = map
        if (!follow) map.moveCamera(CameraUpdate.fitBounds(LatLngBounds.from(coords), 80))
    }

    LaunchedEffect(naverMap, position, bearing) {
        val map = naverMap ?: return@LaunchedEffect
        val (lat, lon) = position ?: return@LaunchedEffect
        val here = LatLng(lat, lon)
        map.locationOverlay.isVisible = true
        map.locationOverlay.position = here
        bearing?.let { map.locationOverlay.bearing = it }
        if (follow) map.moveCamera(CameraUpdate.scrollTo(here))
    }
}
