package com.mixnavuts.app.ui.map

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
import org.maplibre.android.camera.CameraPosition
import org.maplibre.android.camera.CameraUpdateFactory
import org.maplibre.android.geometry.LatLng
import org.maplibre.android.geometry.LatLngBounds
import org.maplibre.android.maps.MapLibreMap
import org.maplibre.android.maps.MapView
import org.maplibre.android.maps.Style
import org.maplibre.android.style.layers.CircleLayer
import org.maplibre.android.style.layers.LineLayer
import org.maplibre.android.style.layers.Property
import org.maplibre.android.style.layers.PropertyFactory
import org.maplibre.android.style.sources.GeoJsonSource
import org.maplibre.geojson.FeatureCollection
import org.maplibre.geojson.LineString
import org.maplibre.geojson.Point

private const val ROUTE = "mixnavuts-route"
private const val CAR = "mixnavuts-car"

/**
 * The engine's own map (/v1/style.json: road network vector tiles, optionally on
 * the 브이월드 base map) rendered by MapLibre, with the route and the car on top.
 */
@Composable
fun MapLibreRouteMap(
    styleUrl: String,
    route: RouteOption?,
    position: Pair<Double, Double>?,
    bearing: Float?,
    follow: Boolean,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val mapView = remember { MapView(context) }
    var map by remember { mutableStateOf<MapLibreMap?>(null) }
    var style by remember { mutableStateOf<Style?>(null) }

    DisposableEffect(lifecycle, mapView) {
        mapView.onCreate(null)
        mapView.getMapAsync { loaded ->
            loaded.setStyle(Style.Builder().fromUri(styleUrl)) { ready ->
                addRouteLayers(ready)
                map = loaded
                style = ready
            }
        }
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

    LaunchedEffect(style, route?.id) {
        val ready = style ?: return@LaunchedEffect
        val points = route?.points.orEmpty()
        val source = ready.getSourceAs<GeoJsonSource>(ROUTE) ?: return@LaunchedEffect
        if (points.size < 2) {
            source.setGeoJson(FeatureCollection.fromFeatures(emptyList()))
            return@LaunchedEffect
        }
        source.setGeoJson(LineString.fromLngLats(points.map { Point.fromLngLat(it.lon, it.lat) }))
        if (!follow) {
            val bounds = LatLngBounds.Builder().includes(points.map { LatLng(it.lat, it.lon) }).build()
            map?.moveCamera(CameraUpdateFactory.newLatLngBounds(bounds, 80))
        }
    }

    LaunchedEffect(style, position, bearing) {
        val ready = style ?: return@LaunchedEffect
        val (lat, lon) = position ?: return@LaunchedEffect
        ready.getSourceAs<GeoJsonSource>(CAR)?.setGeoJson(Point.fromLngLat(lon, lat))
        if (follow) {
            val camera = CameraPosition.Builder()
                .target(LatLng(lat, lon))
                .zoom(16.0)
                .bearing((bearing ?: 0f).toDouble())
                .tilt(45.0)
                .build()
            map?.easeCamera(CameraUpdateFactory.newCameraPosition(camera), 900)
        }
    }
}

private fun addRouteLayers(style: Style) {
    style.addSource(GeoJsonSource(ROUTE))
    style.addSource(GeoJsonSource(CAR))
    style.addLayer(
        LineLayer(ROUTE, ROUTE).withProperties(
            PropertyFactory.lineColor("#1E88E5"),
            PropertyFactory.lineWidth(7f),
            PropertyFactory.lineCap(Property.LINE_CAP_ROUND),
            PropertyFactory.lineJoin(Property.LINE_JOIN_ROUND),
        ),
    )
    style.addLayer(
        CircleLayer(CAR, CAR).withProperties(
            PropertyFactory.circleRadius(8f),
            PropertyFactory.circleColor("#111111"),
            PropertyFactory.circleStrokeColor("#FFFFFF"),
            PropertyFactory.circleStrokeWidth(2f),
        ),
    )
}
