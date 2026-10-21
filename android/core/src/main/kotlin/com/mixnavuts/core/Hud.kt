package com.mixnavuts.core

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.roundToInt

enum class SpeedSource { VEHICLE, GNSS }

/**
 * Everything a HUD, cluster or phone screen shows, already decided and formatted.
 * Screens only lay this out; the look is theirs.
 */
data class HudState(
    val state: GuidanceState,
    val speedKmh: Int?,
    val speedSource: SpeedSource?,
    val limitKmh: Int?,
    val overLimit: Boolean,
    val turn: Turn?,
    val maneuverDistance: String?,
    val maneuverText: String?,
    val thenText: String?,
    val roadAhead: String?,
    val roadName: String,
    val eta: String,
    val remainingDistance: String,
    val remainingTime: String,
)

object Format {
    fun distance(m: Double): String = when {
        m < 50 -> "${(m / 5).roundToInt() * 5} m"
        m < 1_000 -> "${(m / 10).roundToInt() * 10} m"
        m < 10_000 -> String.format(Locale.ROOT, "%.1f km", m / 1_000)
        else -> "${(m / 1_000).roundToInt()} km"
    }

    fun duration(s: Double): String {
        val minutes = (s / 60).roundToInt()
        return if (minutes < 60) "${minutes}분" else "${minutes / 60}시간 ${minutes % 60}분"
    }

    fun clock(epochS: Double, zone: ZoneId): String =
        DateTimeFormatter.ofPattern("HH:mm").format(Instant.ofEpochMilli((epochS * 1000).toLong()).atZone(zone))

    fun won(krw: Int): String = String.format(Locale.ROOT, "%,d원", krw)

    /** Rally-style pace note for the next winding stretch, if it is close. */
    fun roadAhead(curve: Curve?, distanceM: Double?, withinM: Double = 1_500.0): String? {
        if (curve == null || distanceM == null || distanceM > withinM) return null
        val kind = when (curve.direction) {
            "left" -> if (curve.severity >= 0.7) "좌측 급커브" else "좌측 굽은 구간"
            "right" -> if (curve.severity >= 0.7) "우측 급커브" else "우측 굽은 구간"
            else -> "연속 굽은 길"
        }
        return if (distanceM < 1.0) "$kind 주행 중" else "$kind · ${distance(distanceM)} 앞"
    }
}

object Hud {
    fun build(progress: Progress, fix: Fix, vehicleSpeedMps: Double?, zone: ZoneId = ZoneId.systemDefault()): HudState {
        val speedMps = vehicleSpeedMps ?: fix.speedMps
        val speedKmh = speedMps?.let { (it * 3.6).roundToInt() }
        val limit = progress.segment.speedLimitKmh.takeIf { it > 0 }
        val next = progress.nextManeuver
        return HudState(
            state = progress.state,
            speedKmh = speedKmh,
            speedSource = when {
                vehicleSpeedMps != null -> SpeedSource.VEHICLE
                fix.speedMps != null -> SpeedSource.GNSS
                else -> null
            },
            limitKmh = limit,
            overLimit = speedKmh != null && limit != null && speedKmh > limit,
            turn = next?.turn,
            maneuverDistance = progress.distanceToManeuverM?.let { Format.distance(it) },
            maneuverText = when (progress.state) {
                GuidanceState.ARRIVED -> "목적지에 도착했습니다"
                GuidanceState.OFF_ROUTE -> "경로를 벗어났습니다 · 재탐색"
                GuidanceState.ON_ROUTE -> next?.instruction
            },
            thenText = progress.followingManeuver
                ?.takeIf { next != null && it.distanceM - next.distanceM < 300 }
                ?.let { "이어서 ${it.instruction}" },
            roadAhead = Format.roadAhead(progress.nextCurve, progress.distanceToCurveM),
            roadName = progress.segment.roadName,
            eta = Format.clock(progress.eta, zone),
            remainingDistance = Format.distance(progress.remainingM),
            remainingTime = Format.duration(progress.remainingS),
        )
    }
}
