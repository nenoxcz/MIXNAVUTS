package com.mixnavuts.app.ui.map

import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import com.mixnavuts.core.RouteOption
import com.mixnavuts.core.ScreenFit

/**
 * The route on a map: 네이버 지도 when a client ID is configured, otherwise a
 * plain drawing of the route (enough for development and the synthetic city).
 */
@Composable
fun RouteMap(
    route: RouteOption?,
    position: Pair<Double, Double>?,
    follow: Boolean,
    modifier: Modifier = Modifier,
    bearing: Float? = null,
) {
    if (NaverMapSetup.enabled) {
        NaverRouteMap(route, position, bearing, follow, modifier)
    } else {
        RouteDrawing(route, position, modifier)
    }
}

@Composable
fun RouteDrawing(route: RouteOption?, position: Pair<Double, Double>?, modifier: Modifier = Modifier) {
    Canvas(modifier) {
        drawRect(Color(0xFFEDEDED))
        val points = route?.points ?: return@Canvas
        if (points.size < 2) return@Canvas
        val fit = ScreenFit(points, size.width, size.height, 24f)
        val path = Path().apply {
            moveTo(fit.x(points[0].lat, points[0].lon), fit.y(points[0].lat, points[0].lon))
            for (p in points.drop(1)) lineTo(fit.x(p.lat, p.lon), fit.y(p.lat, p.lon))
        }
        drawPath(path, Color(0xFF1E88E5), style = Stroke(width = 10f, cap = StrokeCap.Round, join = StrokeJoin.Round))
        position?.let { (lat, lon) ->
            drawCircle(Color.Black, radius = 14f, center = Offset(fit.x(lat, lon), fit.y(lat, lon)))
        }
    }
}
