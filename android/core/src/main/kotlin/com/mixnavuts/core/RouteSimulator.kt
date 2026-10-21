package com.mixnavuts.core

import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin

/**
 * Drives a route at its predicted speeds, for demos and for testing guidance,
 * Android Auto and CarPlay without a car.
 *
 * `detourAtM`: after this distance the simulated car drifts sideways off the
 * route, which exercises off-route detection and rerouting.
 */
class RouteSimulator(
    private val route: RouteOption,
    private val startEpoch: Double,
    private val detourAtM: Double? = null,
) {
    private val points = route.points
    val durationS: Double get() = route.durationS

    fun fixAt(elapsedS: Double): Fix {
        val t = elapsedS.coerceIn(0.0, route.durationS)
        val segment = route.segments.lastOrNull { it.offsetS <= t } ?: route.segments.first()
        val fraction = if (segment.durationS > 0) ((t - segment.offsetS) / segment.durationS).coerceIn(0.0, 1.0) else 1.0
        val start = points[segment.startIndex].distanceM
        val end = points[segment.endIndex].distanceM
        val along = start + fraction * (end - start)

        var i = segment.startIndex
        while (i < segment.endIndex - 1 && points[i + 1].distanceM < along) i++
        val a = points[i]
        val b = points[i + 1]
        val f = if (b.distanceM > a.distanceM) ((along - a.distanceM) / (b.distanceM - a.distanceM)).coerceIn(0.0, 1.0) else 0.0
        var lat = a.lat + f * (b.lat - a.lat)
        var lon = a.lon + f * (b.lon - a.lon)

        val projection = LocalProjection(a.lat, a.lon)
        val heading = atan2(projection.y(b.lat), projection.x(b.lon))
        val drift = detourAtM?.let { (along - it).coerceAtLeast(0.0) } ?: 0.0
        if (drift > 0) { // move to the right of the direction of travel
            lat = projection.lat(projection.y(lat) - cos(heading) * drift)
            lon = projection.lon(projection.x(lon) + sin(heading) * drift)
        }
        val speed = if (segment.durationS > 0) segment.lengthM / segment.durationS else 0.0
        val bearing = (90.0 - Math.toDegrees(heading) + 360.0) % 360.0
        return Fix(startEpoch + t, lat, lon, speedMps = speed, accuracyM = 5.0, bearingDeg = bearing)
    }
}
