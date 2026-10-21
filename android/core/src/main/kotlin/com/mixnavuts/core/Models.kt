package com.mixnavuts.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/** JSON settings shared by every API call (see docs/API.md). */
val MixnavutsJson = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    encodeDefaults = true
}

@Serializable
data class Place(
    val name: String,
    val lat: Double,
    val lon: Double,
    val address: String = "",
    val category: String = "",
    val source: String = "network",
)

/** Network places are sent by name; search results (e.g. 카카오) by coordinate. */
fun Place.toEndpoint(): Endpoint = if (source == "network") Endpoint.place(name) else Endpoint.at(lat, lon)

@Serializable
data class PlacesResponse(val synthetic: Boolean = false, val places: List<Place> = emptyList())

@Serializable
data class SearchResponse(val provider: String = "", val results: List<Place> = emptyList())

/** Origin or destination: a named place of the network, or a coordinate. */
@Serializable
data class Endpoint(val place: String? = null, val lat: Double? = null, val lon: Double? = null) {
    companion object {
        fun place(name: String) = Endpoint(place = name)
        fun at(lat: Double, lon: Double) = Endpoint(lat = lat, lon = lon)
    }
}

@Serializable
data class RouteRequest(
    val origin: Endpoint,
    val destination: Endpoint,
    val depart: Double? = null,
    val mode: String = "balanced",
    val k: Int = 4,
)

@Serializable
data class LiveInfo(
    val source: String = "none",
    @SerialName("as_of") val asOf: Double? = null,
    val incidents: Int = 0,
)

@Serializable
data class RoutesResponse(
    val synthetic: Boolean = false,
    val network: String = "",
    val mode: String = "balanced",
    val depart: Double = 0.0,
    val candidates: Int = 0,
    @SerialName("candidate_sources") val candidateSources: Map<String, Int> = emptyMap(),
    val live: LiveInfo = LiveInfo(),
    val routes: List<RouteOption> = emptyList(),
)

@Serializable
data class RouteOption(
    val id: String,
    val labels: List<String>,
    val depart: Double,
    val arrival: Double,
    @SerialName("duration_s") val durationS: Double,
    @SerialName("distance_m") val distanceM: Double,
    @SerialName("toll_krw") val tollKrw: Int,
    @SerialName("highway_share") val highwayShare: Double,
    val winding: Double,
    val summary: String,
    /** [lat, lon, distance along the route in metres] per vertex. */
    val geometry: List<List<Double>>,
    val segments: List<Segment>,
    val maneuvers: List<Maneuver>,
    val curves: List<Curve> = emptyList(),
    /** Cameras, traffic lights and speed bumps along the route, in driving order. */
    val alerts: List<RouteAlert> = emptyList(),
) {
    val points: List<RoutePoint> by lazy { geometry.map { RoutePoint(it[0], it[1], it[2]) } }
}

data class RoutePoint(val lat: Double, val lon: Double, val distanceM: Double)

@Serializable
data class Segment(
    @SerialName("start_index") val startIndex: Int,
    @SerialName("end_index") val endIndex: Int,
    @SerialName("length_m") val lengthM: Double,
    @SerialName("speed_limit_kmh") val speedLimitKmh: Int,
    @SerialName("road_name") val roadName: String,
    @SerialName("road_class") val roadClass: String,
    val curvature: Double = 0.0,
    @SerialName("toll_krw") val tollKrw: Int = 0,
    @SerialName("offset_s") val offsetS: Double,
    @SerialName("duration_s") val durationS: Double,
    @SerialName("link_id") val linkId: String? = null,
)

@Serializable
data class Maneuver(
    @SerialName("point_index") val pointIndex: Int,
    @SerialName("distance_m") val distanceM: Double,
    val type: String,
    val modifier: String,
    @SerialName("road_name") val roadName: String,
    val instruction: String,
    /** Which lanes to be in (from 정밀도로지도, or the usual lanes for the maneuver). */
    val lanes: LaneHint? = null,
) {
    val turn: Turn get() = Turn.of(type, modifier)
}

/** `recommended` counts from 1 = 1차로 (leftmost). */
@Serializable
data class LaneHint(val count: Int, val recommended: List<Int>)

@Serializable
data class RouteAlert(
    /** speed_camera, signal_camera, section_camera, traffic_light, speed_bump */
    val type: String,
    @SerialName("distance_m") val distanceM: Double,
    @SerialName("speed_limit_kmh") val speedLimitKmh: Int? = null,
    val label: String,
    val note: String? = null,
)

@Serializable
data class Curve(
    @SerialName("start_m") val startM: Double,
    @SerialName("end_m") val endM: Double,
    val direction: String,
    val severity: Double,
)

/** One maneuver symbol, so every screen (phone, Android Auto, cluster) picks the same icon. */
enum class Turn(val angleDeg: Double) {
    DEPART(0.0),
    STRAIGHT(0.0),
    SLIGHT_LEFT(-40.0),
    LEFT(-90.0),
    SHARP_LEFT(-135.0),
    SLIGHT_RIGHT(40.0),
    RIGHT(90.0),
    SHARP_RIGHT(135.0),
    UTURN(180.0),
    RAMP_LEFT(-30.0),
    RAMP_RIGHT(30.0),
    EXIT_LEFT(-30.0),
    EXIT_RIGHT(30.0),
    FORK_LEFT(-20.0),
    FORK_RIGHT(20.0),
    ARRIVE(0.0);

    companion object {
        fun of(type: String, modifier: String): Turn {
            val left = "left" in modifier
            return when (type) {
                "depart" -> DEPART
                "arrive" -> ARRIVE
                "ramp_on" -> if (left) RAMP_LEFT else RAMP_RIGHT
                "ramp_off" -> if (left) EXIT_LEFT else EXIT_RIGHT
                "fork" -> if (left) FORK_LEFT else FORK_RIGHT
                else -> when (modifier) {
                    "slight_left" -> SLIGHT_LEFT
                    "left" -> LEFT
                    "sharp_left" -> SHARP_LEFT
                    "slight_right" -> SLIGHT_RIGHT
                    "right" -> RIGHT
                    "sharp_right" -> SHARP_RIGHT
                    "uturn" -> UTURN
                    else -> STRAIGHT
                }
            }
        }
    }
}
