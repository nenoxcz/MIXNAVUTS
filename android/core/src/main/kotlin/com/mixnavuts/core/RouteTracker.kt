package com.mixnavuts.core

/** A position report from GNSS, the vehicle or the simulator. `time` is epoch seconds. */
data class Fix(
    val time: Double,
    val lat: Double,
    val lon: Double,
    val speedMps: Double? = null,
    val accuracyM: Double? = null,
    val bearingDeg: Double? = null,
)

enum class GuidanceState { ON_ROUTE, OFF_ROUTE, ARRIVED }

data class Progress(
    val state: GuidanceState,
    val alongM: Double,
    val offsetM: Double,
    val remainingM: Double,
    val remainingS: Double,
    val eta: Double,
    val segment: Segment,
    val nextManeuver: Maneuver?,
    val distanceToManeuverM: Double?,
    val timeToManeuverS: Double?,
    val followingManeuver: Maneuver?,
    val nextCurve: Curve?,
    val distanceToCurveM: Double?,
    val snappedLat: Double,
    val snappedLon: Double,
)

/**
 * Matches fixes to the route and works out what is next.
 *
 * Matching only looks a little behind and a good way ahead of the last match,
 * so a route that passes the same place twice does not make progress jump.
 * A fix counts as off the route when it is further than
 * max(offRouteM, 1.5 × accuracy) from it; `offRouteFixes` of those in a row
 * report OFF_ROUTE (one bad GNSS reading is not a missed turn).
 */
class RouteTracker(
    val route: RouteOption,
    private val offRouteM: Double = 50.0,
    private val offRouteFixes: Int = 3,
    private val arrivalM: Double = 25.0,
) {
    private val points = route.points
    private val projection = LocalProjection(points.first().lat, points.first().lon)
    private val xs = points.map { projection.x(it.lon) }
    private val ys = points.map { projection.y(it.lat) }
    private val segmentOfPiece = IntArray(maxOf(1, points.size - 1)).also { owner ->
        route.segments.forEachIndexed { s, segment ->
            for (i in segment.startIndex until segment.endIndex) owner[i] = s
        }
    }
    private val total = points.last().distanceM

    private var piece = -1
    private var along = 0.0
    private var misses = 0
    private var arrived = false

    fun update(fix: Fix): Progress {
        val px = projection.x(fix.lon)
        val py = projection.y(fix.lat)
        val range = if (piece < 0) 0 until points.size - 1 else maxOf(0, piece - 3)..minOf(points.size - 2, piece + 40)
        var bestPiece = 0
        var bestT = 0.0
        var bestD = Double.MAX_VALUE
        for (i in range) {
            val (t, d) = projectOnSegment(px, py, xs[i], ys[i], xs[i + 1], ys[i + 1])
            if (d < bestD - 1e-9) {
                bestPiece = i
                bestT = t
                bestD = d
            }
        }
        val limit = maxOf(offRouteM, 1.5 * (fix.accuracyM ?: 0.0))
        if (bestD <= limit) {
            misses = 0
            piece = bestPiece
            along = points[bestPiece].distanceM + bestT * (points[bestPiece + 1].distanceM - points[bestPiece].distanceM)
        } else {
            misses++
            if (piece < 0) piece = bestPiece
        }
        if (total - along <= arrivalM) arrived = true
        val state = when {
            arrived -> GuidanceState.ARRIVED
            misses >= offRouteFixes -> GuidanceState.OFF_ROUTE
            else -> GuidanceState.ON_ROUTE
        }
        return progressAt(fix, state, bestD)
    }

    /** Predicted seconds from departure until the route reaches `distanceM`. */
    fun predictedElapsedAt(distanceM: Double): Double {
        val segment = route.segments.lastOrNull { points[it.startIndex].distanceM <= distanceM } ?: route.segments.first()
        val segStart = points[segment.startIndex].distanceM
        val segEnd = points[segment.endIndex].distanceM
        val fraction = if (segEnd > segStart) ((distanceM - segStart) / (segEnd - segStart)).coerceIn(0.0, 1.0) else 1.0
        return segment.offsetS + fraction * segment.durationS
    }

    private fun progressAt(fix: Fix, state: GuidanceState, offset: Double): Progress {
        val segment = route.segments[segmentOfPiece[piece.coerceIn(0, segmentOfPiece.size - 1)]]
        val elapsed = predictedElapsedAt(along)
        val remainingS = (route.durationS - elapsed).coerceAtLeast(0.0)

        val upcoming = route.maneuvers.filter { it.type != "depart" && it.distanceM > along + 1.0 }
        val next = upcoming.firstOrNull()
        val curve = route.curves.firstOrNull { it.endM > along }

        val p0 = points[piece.coerceIn(0, points.size - 2)]
        val p1 = points[(piece + 1).coerceIn(1, points.size - 1)]
        val pieceLen = p1.distanceM - p0.distanceM
        val t = if (pieceLen > 0) ((along - p0.distanceM) / pieceLen).coerceIn(0.0, 1.0) else 0.0
        return Progress(
            state = state,
            alongM = along,
            offsetM = offset,
            remainingM = (total - along).coerceAtLeast(0.0),
            remainingS = remainingS,
            eta = fix.time + remainingS,
            segment = segment,
            nextManeuver = next,
            distanceToManeuverM = next?.let { it.distanceM - along },
            timeToManeuverS = next?.let { (predictedElapsedAt(it.distanceM) - elapsed).coerceAtLeast(0.0) },
            followingManeuver = upcoming.getOrNull(1),
            nextCurve = curve,
            distanceToCurveM = curve?.let { (it.startM - along).coerceAtLeast(0.0) },
            snappedLat = p0.lat + t * (p1.lat - p0.lat),
            snappedLon = p0.lon + t * (p1.lon - p0.lon),
        )
    }
}
