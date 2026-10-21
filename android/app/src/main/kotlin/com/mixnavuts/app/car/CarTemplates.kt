package com.mixnavuts.app.car

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import androidx.car.app.model.Action
import androidx.car.app.model.ActionStrip
import androidx.car.app.model.CarIcon
import androidx.car.app.model.DateTimeWithZone
import androidx.car.app.model.Distance
import androidx.car.app.model.Template
import androidx.car.app.navigation.model.Destination
import androidx.car.app.navigation.model.Maneuver
import androidx.car.app.navigation.model.MessageInfo
import androidx.car.app.navigation.model.NavigationTemplate
import androidx.car.app.navigation.model.RoutingInfo
import androidx.car.app.navigation.model.Step
import androidx.car.app.navigation.model.TravelEstimate
import androidx.car.app.navigation.model.Trip
import androidx.core.graphics.drawable.IconCompat
import com.mixnavuts.app.NavState
import com.mixnavuts.core.GuidanceState
import com.mixnavuts.core.NavUpdate
import com.mixnavuts.core.Turn
import java.util.TimeZone
import kotlin.math.cos
import kotlin.math.roundToLong
import kotlin.math.sin
import com.mixnavuts.core.Maneuver as RouteManeuver

/** Builds Android Auto templates and the Trip sent to the cluster/HUD from app state. */
object CarTemplates {
    private val icons = mutableMapOf<Turn, CarIcon>()

    fun navigationTemplate(state: NavState, onStop: () -> Unit): Template {
        val strip = ActionStrip.Builder()
            .addAction(Action.Builder().setTitle("종료").setOnClickListener { onStop() }.build())
            .build()
        val builder = NavigationTemplate.Builder().setActionStrip(strip)
        val update = state.navigation
        if (update == null) {
            builder.setNavigationInfo(RoutingInfo.Builder().setLoading(true).build())
            return builder.build()
        }
        val progress = update.progress
        when (progress.state) {
            GuidanceState.ARRIVED ->
                builder.setNavigationInfo(MessageInfo.Builder("목적지 도착").setText(state.destinationName).build())
            GuidanceState.OFF_ROUTE ->
                builder.setNavigationInfo(MessageInfo.Builder("경로 재탐색 중").build())
            GuidanceState.ON_ROUTE -> {
                val next = progress.nextManeuver
                if (next != null) {
                    val routing = RoutingInfo.Builder().setCurrentStep(step(next), distance(progress.distanceToManeuverM ?: 0.0))
                    progress.followingManeuver?.let { routing.setNextStep(step(it)) }
                    builder.setNavigationInfo(routing.build())
                } else {
                    builder.setNavigationInfo(MessageInfo.Builder(update.hud.roadName).build())
                }
                builder.setDestinationTravelEstimate(estimate(progress.remainingM, progress.eta, progress.remainingS))
            }
        }
        return builder.build()
    }

    /** What NavigationManager.updateTrip sends to the instrument cluster and HUD. */
    fun trip(update: NavUpdate, destinationName: String): Trip {
        val progress = update.progress
        val builder = Trip.Builder().setLoading(false).setCurrentRoad(progress.segment.roadName)
        progress.nextManeuver?.let { next ->
            val toNext = progress.timeToManeuverS ?: 0.0
            builder.addStep(step(next), estimate(progress.distanceToManeuverM ?: 0.0, update.fix.time + toNext, toNext))
        }
        val destination = Destination.Builder().setName(destinationName.ifBlank { "목적지" }).build()
        builder.addDestination(destination, estimate(progress.remainingM, progress.eta, progress.remainingS))
        return builder.build()
    }

    fun step(maneuver: RouteManeuver): Step =
        Step.Builder(maneuver.instruction)
            .setManeuver(Maneuver.Builder(maneuverType(maneuver.turn)).setIcon(icon(maneuver.turn)).build())
            .setRoad(maneuver.roadName)
            .build()

    fun distance(meters: Double): Distance = when {
        meters >= 10_000 -> Distance.create(meters / 1_000, Distance.UNIT_KILOMETERS)
        meters >= 1_000 -> Distance.create(meters / 1_000, Distance.UNIT_KILOMETERS_P1)
        else -> Distance.create(((meters / 10).roundToLong() * 10).toDouble(), Distance.UNIT_METERS)
    }

    fun estimate(meters: Double, arrivalEpochS: Double, remainingS: Double): TravelEstimate =
        TravelEstimate.Builder(
            distance(meters),
            DateTimeWithZone.create((arrivalEpochS * 1000).toLong(), TimeZone.getDefault()),
        ).setRemainingTimeSeconds(remainingS.roundToLong().coerceAtLeast(0)).build()

    private fun maneuverType(turn: Turn): Int = when (turn) {
        Turn.DEPART -> Maneuver.TYPE_DEPART
        Turn.STRAIGHT -> Maneuver.TYPE_STRAIGHT
        Turn.SLIGHT_LEFT -> Maneuver.TYPE_TURN_SLIGHT_LEFT
        Turn.LEFT -> Maneuver.TYPE_TURN_NORMAL_LEFT
        Turn.SHARP_LEFT -> Maneuver.TYPE_TURN_SHARP_LEFT
        Turn.SLIGHT_RIGHT -> Maneuver.TYPE_TURN_SLIGHT_RIGHT
        Turn.RIGHT -> Maneuver.TYPE_TURN_NORMAL_RIGHT
        Turn.SHARP_RIGHT -> Maneuver.TYPE_TURN_SHARP_RIGHT
        Turn.UTURN -> Maneuver.TYPE_U_TURN_LEFT // 우측통행: 유턴은 왼쪽으로
        Turn.RAMP_LEFT -> Maneuver.TYPE_ON_RAMP_SLIGHT_LEFT
        Turn.RAMP_RIGHT -> Maneuver.TYPE_ON_RAMP_SLIGHT_RIGHT
        Turn.EXIT_LEFT -> Maneuver.TYPE_OFF_RAMP_SLIGHT_LEFT
        Turn.EXIT_RIGHT -> Maneuver.TYPE_OFF_RAMP_SLIGHT_RIGHT
        Turn.FORK_LEFT -> Maneuver.TYPE_FORK_LEFT
        Turn.FORK_RIGHT -> Maneuver.TYPE_FORK_RIGHT
        Turn.ARRIVE -> Maneuver.TYPE_DESTINATION
    }

    /** Placeholder arrow icons drawn in code; replace with the designed set. */
    private fun icon(turn: Turn): CarIcon = icons.getOrPut(turn) {
        CarIcon.Builder(IconCompat.createWithBitmap(arrow(turn))).build()
    }

    private fun arrow(turn: Turn, size: Int = 128): Bitmap {
        val bitmap = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            style = Paint.Style.STROKE
            strokeWidth = size * 0.11f
            strokeCap = Paint.Cap.ROUND
            strokeJoin = Paint.Join.ROUND
        }
        val s = size.toFloat()
        val cx = s / 2
        if (turn == Turn.ARRIVE) {
            canvas.drawCircle(cx, s * 0.42f, s * 0.2f, paint)
            canvas.drawLine(cx, s * 0.62f, cx, s * 0.88f, paint)
            return bitmap
        }
        val path = Path()
        val (tipX, tipY, headingRad) = if (turn == Turn.UTURN) {
            path.moveTo(cx + s * 0.18f, s * 0.88f)
            path.lineTo(cx + s * 0.18f, s * 0.4f)
            path.quadTo(cx + s * 0.18f, s * 0.12f, cx, s * 0.12f)
            path.quadTo(cx - s * 0.18f, s * 0.12f, cx - s * 0.18f, s * 0.4f)
            path.lineTo(cx - s * 0.18f, s * 0.62f)
            Triple(cx - s * 0.18f, s * 0.62f, Math.PI)
        } else {
            val angle = Math.toRadians(turn.angleDeg)
            path.moveTo(cx, s * 0.9f)
            path.lineTo(cx, s * 0.52f)
            val tipX = cx + (sin(angle) * s * 0.36).toFloat()
            val tipY = s * 0.52f - (cos(angle) * s * 0.36).toFloat()
            path.lineTo(tipX, tipY)
            Triple(tipX, tipY, angle)
        }
        for (side in listOf(-1, 1)) { // arrow head
            val a = headingRad + Math.PI + side * Math.toRadians(35.0)
            path.moveTo(tipX, tipY)
            path.lineTo(tipX + (sin(a) * s * 0.2).toFloat(), tipY - (cos(a) * s * 0.2).toFloat())
        }
        canvas.drawPath(path, paint)
        return bitmap
    }
}
