package com.mixnavuts.core

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.time.ZoneId

private val KST: ZoneId = ZoneId.of("Asia/Seoul")

private fun fixture(name: String): String {
    val dir = System.getProperty("mixnavuts.fixtures") ?: "../../shared/fixtures"
    return File(dir, name).readText()
}

private val response: RoutesResponse by lazy { MixnavutsJson.decodeFromString(RoutesResponse.serializer(), fixture("routes_response.json")) }

private fun motorwayRoute() = response.routes.first { it.highwayShare > 0.5 }

class DecodeTest {
    @Test
    fun decodesTheSharedFixture() {
        assertTrue(response.synthetic)
        assertTrue(response.candidates > 50)
        assertEquals(3, response.routes.size)
        val route = response.routes.first()
        assertEquals(route.geometry.size, route.points.size)
        assertEquals(route.segments.last().endIndex, route.points.size - 1)
        assertEquals("depart", route.maneuvers.first().type)
        assertEquals("arrive", route.maneuvers.last().type)
    }

    @Test
    fun decodesPlaces() {
        val places = MixnavutsJson.decodeFromString(PlacesResponse.serializer(), fixture("places_response.json"))
        assertTrue(places.places.any { it.name == "시청" })
    }

    @Test
    fun encodesRequestsWithoutNulls() {
        val json = MixnavutsJson.encodeToString(RouteRequest.serializer(), RouteRequest(Endpoint.place("시청"), Endpoint.at(37.5, 127.0)))
        assertEquals("""{"origin":{"place":"시청"},"destination":{"lat":37.5,"lon":127.0},"mode":"balanced","k":4}""", json)
    }

    @Test
    fun mapsManeuversToTurns() {
        assertEquals(Turn.LEFT, Turn.of("turn", "left"))
        assertEquals(Turn.RAMP_RIGHT, Turn.of("ramp_on", "right"))
        assertEquals(Turn.EXIT_LEFT, Turn.of("ramp_off", "slight_left"))
        assertEquals(Turn.ARRIVE, Turn.of("arrive", "straight"))
        assertEquals(Turn.STRAIGHT, Turn.of("continue", "straight"))
    }
}

class TrackerTest {
    @Test
    fun followsASimulatedDriveToArrival() {
        val route = motorwayRoute()
        val sim = RouteSimulator(route, startEpoch = route.depart)
        val tracker = RouteTracker(route)
        var lastAlong = -1.0
        val seenManeuvers = mutableSetOf<Int>()
        var t = 0.0
        var progress: Progress? = null
        while (t <= sim.durationS) {
            progress = tracker.update(sim.fixAt(t))
            assertTrue("progress went backwards at t=$t", progress.alongM >= lastAlong - 0.5)
            assertTrue(progress.state != GuidanceState.OFF_ROUTE)
            lastAlong = progress.alongM
            progress.nextManeuver?.let { seenManeuvers.add(it.pointIndex) }
            t += 2.0
        }
        progress = tracker.update(sim.fixAt(sim.durationS))
        assertEquals(GuidanceState.ARRIVED, progress.state)
        assertEquals(route.maneuvers.count { it.type != "depart" }, seenManeuvers.size)
    }

    @Test
    fun remainingTimeFollowsThePrediction() {
        val route = motorwayRoute()
        val sim = RouteSimulator(route, startEpoch = route.depart)
        val tracker = RouteTracker(route)
        val halfway = route.durationS / 2
        val progress = tracker.update(sim.fixAt(halfway))
        assertEquals(route.durationS - halfway, progress.remainingS, 2.0)
        assertEquals(route.arrival, progress.eta, 2.0)
        val toManeuver = progress.timeToManeuverS!!
        assertTrue(toManeuver in 0.0..progress.remainingS)
    }

    @Test
    fun placeEndpoints() {
        assertEquals(Endpoint.place("시청"), Place("시청", 37.0, 126.0).toEndpoint())
        assertEquals(Endpoint.at(37.55, 126.97), Place("서울역", 37.55, 126.97, source = "kakao").toEndpoint())
    }

    @Test
    fun detectsLeavingTheRouteAfterSeveralFixes() {
        val route = motorwayRoute()
        val sim = RouteSimulator(route, startEpoch = route.depart, detourAtM = 2_000.0)
        val tracker = RouteTracker(route)
        val states = (0..900 step 5).map { tracker.update(sim.fixAt(it.toDouble())).state }
        assertTrue(GuidanceState.OFF_ROUTE in states)
        val firstOff = states.indexOf(GuidanceState.OFF_ROUTE)
        assertTrue("needs consecutive misses", states.subList(0, firstOff).count { it == GuidanceState.ON_ROUTE } > 3)
    }

    @Test
    fun singleBadFixIsTolerated() {
        val route = motorwayRoute()
        val tracker = RouteTracker(route)
        val start = route.points[0]
        tracker.update(Fix(route.depart, start.lat, start.lon))
        val wild = tracker.update(Fix(route.depart + 1, start.lat + 0.01, start.lon))
        assertEquals(GuidanceState.ON_ROUTE, wild.state)
    }
}

class HudTest {
    @Test
    fun formatsDistancesAndTimes() {
        assertEquals("35 m", Format.distance(33.0))
        assertEquals("350 m", Format.distance(348.0))
        assertEquals("1.2 km", Format.distance(1_234.0))
        assertEquals("23 km", Format.distance(22_600.0))
        assertEquals("27분", Format.duration(27 * 60.0 + 10))
        assertEquals("1시간 5분", Format.duration(65 * 60.0))
        assertEquals("08:10", Format.clock(1_792_537_800.0, KST))
        assertEquals("1,860원", Format.won(1_860))
    }

    @Test
    fun paceNotes() {
        val curve = Curve(1_000.0, 2_000.0, "right", 0.85)
        assertEquals("우측 급커브 · 400 m 앞", Format.roadAhead(curve, 400.0))
        assertEquals("우측 급커브 주행 중", Format.roadAhead(curve, 0.0))
        assertNull(Format.roadAhead(curve, 5_000.0))
        assertEquals("연속 굽은 길 · 200 m 앞", Format.roadAhead(Curve(0.0, 1.0, "mixed", 0.4), 200.0))
    }

    @Test
    fun hudPrefersVehicleSpeedAndFlagsSpeeding() {
        val route = motorwayRoute()
        val sim = RouteSimulator(route, startEpoch = route.depart)
        val tracker = RouteTracker(route)
        val fix = sim.fixAt(60.0)
        val progress = tracker.update(fix)
        val gnss = Hud.build(progress, fix, vehicleSpeedMps = null, zone = KST)
        assertEquals(SpeedSource.GNSS, gnss.speedSource)
        val fast = Hud.build(progress, fix, vehicleSpeedMps = (progress.segment.speedLimitKmh + 20) / 3.6, zone = KST)
        assertEquals(SpeedSource.VEHICLE, fast.speedSource)
        assertTrue(fast.overLimit)
        assertNotNull(fast.maneuverText)
        assertNotNull(fast.maneuverDistance)
    }
}

class LaneAndAlertTest {
    @Test
    fun fixtureCarriesLanesAndAlerts() {
        val route = motorwayRoute()
        assertTrue(route.maneuvers.any { it.lanes != null })
        assertTrue(route.alerts.any { it.type == "speed_camera" && it.speedLimitKmh == 100 })
        assertEquals(route.alerts.sortedBy { it.distanceM }, route.alerts)
    }

    @Test
    fun hudShowsLanesNearTheManeuverOnly() {
        val route = motorwayRoute()
        val guided = route.maneuvers.first { it.lanes != null }
        val tracker = RouteTracker(route)
        val sim = RouteSimulator(route, startEpoch = route.depart)
        var shownNear = false
        var shownFar = false
        var t = 0.0
        while (t < route.durationS) {
            val fix = sim.fixAt(t)
            val progress = tracker.update(fix)
            val hud = Hud.build(progress, fix, null, KST)
            if (progress.nextManeuver == guided && hud.lanes != null) {
                if (progress.distanceToManeuverM!! <= Hud.LANES_WITHIN_M) shownNear = true else shownFar = true
                assertEquals(guided.lanes!!.count, hud.lanes!!.size)
                assertEquals(guided.lanes!!.recommended, hud.lanes!!.withIndex().filter { it.value }.map { it.index + 1 })
            }
            t += 3.0
        }
        assertTrue(shownNear)
        assertTrue(!shownFar)
    }

    @Test
    fun cameraAlertAppearsInRange() {
        val route = motorwayRoute()
        val camera = route.alerts.first { it.type == "speed_camera" }
        val tracker = RouteTracker(route)
        val sim = RouteSimulator(route, startEpoch = route.depart)
        val texts = mutableListOf<String>()
        var t = 0.0
        while (t < route.durationS) {
            val fix = sim.fixAt(t)
            val progress = tracker.update(fix)
            val hud = Hud.build(progress, fix, null, KST)
            if (progress.nextAlert == camera) {
                val distance = progress.distanceToAlertM!!
                if (distance > 800) assertNull(hud.alert) else hud.alert?.let { texts += it }
            }
            t += 2.0
        }
        assertTrue(texts.isNotEmpty())
        assertTrue(texts.all { it.startsWith("과속 단속 100") })
        assertEquals("과속방지턱 · 150 m 앞", Format.alert(RouteAlert("speed_bump", 0.0, label = "과속방지턱"), 150.0))
        assertNull(Format.alert(RouteAlert("speed_bump", 0.0, label = "과속방지턱"), 400.0))
    }
}

class SessionTest {
    private class FakeApi(val reply: RouteOption) : RoutesApi {
        val requests = mutableListOf<RouteRequest>()
        override suspend fun routes(request: RouteRequest): RoutesResponse {
            requests += request
            return RoutesResponse(routes = listOf(reply))
        }
    }

    @Test
    fun reroutesOnceWhenOffRoute() = runBlocking {
        val route = motorwayRoute()
        val replacement = response.routes.first { it.id != route.id }
        val api = FakeApi(replacement)
        val session = NavigationSession(api, route, Endpoint.place("동부산업단지"), "balanced", KST)
        val sim = RouteSimulator(route, startEpoch = route.depart, detourAtM = 2_000.0)
        var rerouted = 0
        for (t in 0..600 step 5) {
            if (session.onFix(sim.fixAt(t.toDouble())).rerouted) rerouted++
            if (rerouted > 0) break
        }
        assertEquals(1, rerouted)
        assertEquals(replacement.id, session.route.id)
        val request = api.requests.single()
        assertNotNull(request.origin.lat)
        assertEquals("동부산업단지", request.destination.place)
        assertEquals(1, request.k)
    }

    @Test
    fun reportsRerouteFailureWithoutThrowing() = runBlocking {
        val route = motorwayRoute()
        val api = object : RoutesApi {
            override suspend fun routes(request: RouteRequest): RoutesResponse = throw ApiException(503, "engine down")
        }
        val session = NavigationSession(api, route, Endpoint.place("동부산업단지"), "balanced", KST)
        val sim = RouteSimulator(route, startEpoch = route.depart, detourAtM = 1_000.0)
        val errors = (0..600 step 5).mapNotNull { session.onFix(sim.fixAt(it.toDouble())).rerouteError }
        assertTrue(errors.isNotEmpty())
        assertEquals("engine down", errors.first())
        assertEquals(route.id, session.route.id)
    }
}

class ScreenFitTest {
    @Test
    fun fitsRouteInsideTheBox() {
        val route = motorwayRoute()
        val fit = ScreenFit(route.points, 800f, 400f, 20f)
        for (p in route.points) {
            val x = fit.x(p.lat, p.lon)
            val y = fit.y(p.lat, p.lon)
            assertTrue(x in 19.9f..780.1f && y in 19.9f..380.1f)
        }
    }
}
