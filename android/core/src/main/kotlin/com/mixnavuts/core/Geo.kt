package com.mixnavuts.core

import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.sin
import kotlin.math.sqrt

const val EARTH_RADIUS_M = 6_371_008.8

fun haversineM(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val p1 = Math.toRadians(lat1)
    val p2 = Math.toRadians(lat2)
    val dp = p2 - p1
    val dl = Math.toRadians(lon2 - lon1)
    val h = sin(dp / 2) * sin(dp / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2)
    return 2 * EARTH_RADIUS_M * asin(sqrt(h))
}

/** Equirectangular projection around a reference point; metres east (x) and north (y). */
class LocalProjection(private val lat0: Double, private val lon0: Double) {
    private val cosLat0 = cos(Math.toRadians(lat0))

    fun x(lon: Double) = Math.toRadians(lon - lon0) * EARTH_RADIUS_M * cosLat0
    fun y(lat: Double) = Math.toRadians(lat - lat0) * EARTH_RADIUS_M
    fun lat(y: Double) = lat0 + Math.toDegrees(y / EARTH_RADIUS_M)
    fun lon(x: Double) = lon0 + Math.toDegrees(x / (EARTH_RADIUS_M * cosLat0))
}

/** Closest point on segment a→b to p: (fraction along the segment, distance). */
internal fun projectOnSegment(px: Double, py: Double, ax: Double, ay: Double, bx: Double, by: Double): Pair<Double, Double> {
    val dx = bx - ax
    val dy = by - ay
    val len2 = dx * dx + dy * dy
    val t = if (len2 == 0.0) 0.0 else (((px - ax) * dx + (py - ay) * dy) / len2).coerceIn(0.0, 1.0)
    return t to hypot(px - (ax + t * dx), py - (ay + t * dy))
}

/**
 * Fits a route into a w×h screen box, north up. Both the phone map fallback and
 * the Android Auto surface draw through this.
 */
class ScreenFit(points: List<RoutePoint>, private val width: Float, private val height: Float, padding: Float) {
    private val projection = LocalProjection(points.first().lat, points.first().lon)
    private val minX: Double
    private val maxY: Double
    private val scale: Double
    private val offsetX: Double
    private val offsetY: Double

    init {
        val xs = points.map { projection.x(it.lon) }
        val ys = points.map { projection.y(it.lat) }
        minX = xs.min()
        maxY = ys.max()
        val spanX = (xs.max() - minX).coerceAtLeast(1.0)
        val spanY = (maxY - ys.min()).coerceAtLeast(1.0)
        val usableW = (width - 2 * padding).coerceAtLeast(1f)
        val usableH = (height - 2 * padding).coerceAtLeast(1f)
        scale = minOf(usableW / spanX, usableH / spanY)
        offsetX = padding + (usableW - spanX * scale) / 2
        offsetY = padding + (usableH - spanY * scale) / 2
    }

    fun x(lat: Double, lon: Double): Float = (offsetX + (projection.x(lon) - minX) * scale).toFloat()
    fun y(lat: Double, lon: Double): Float = (offsetY + (maxY - projection.y(lat)) * scale).toFloat()
}
