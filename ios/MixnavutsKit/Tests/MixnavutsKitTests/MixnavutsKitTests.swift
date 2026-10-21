import XCTest
@testable import MixnavutsKit

private let kst = TimeZone(identifier: "Asia/Seoul")!

/// The same API samples the Android core tests read (shared/fixtures).
private func fixture(_ name: String) throws -> Data {
    let repo = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent() // MixnavutsKitTests
        .deletingLastPathComponent() // Tests
        .deletingLastPathComponent() // MixnavutsKit
        .deletingLastPathComponent() // ios
        .deletingLastPathComponent() // repository root
    return try Data(contentsOf: repo.appendingPathComponent("shared/fixtures/\(name)"))
}

private func loadRoutes() throws -> RoutesResponse {
    try mixnavutsDecoder.decode(RoutesResponse.self, from: fixture("routes_response.json"))
}

private func motorwayRoute() throws -> RouteOption {
    try XCTUnwrap(loadRoutes().routes.first { $0.highwayShare > 0.5 })
}

final class DecodeTests: XCTestCase {
    func testDecodesSharedFixture() throws {
        let response = try loadRoutes()
        XCTAssertTrue(response.synthetic)
        XCTAssertGreaterThan(response.candidates, 50)
        XCTAssertEqual(response.routes.count, 3)
        let route = response.routes[0]
        XCTAssertEqual(route.segments.last?.endIndex, route.points.count - 1)
        XCTAssertEqual(route.maneuvers.first?.type, "depart")
        XCTAssertEqual(route.maneuvers.last?.type, "arrive")
        XCTAssertNotNil(response.candidateSources["toll_free"])
    }

    func testDecodesPlaces() throws {
        let places = try mixnavutsDecoder.decode(PlacesResponse.self, from: fixture("places_response.json"))
        XCTAssertTrue(places.places.contains { $0.name == "시청" })
    }

    func testEncodesRequestWithoutNulls() throws {
        let request = RouteRequest(origin: .place("시청"), destination: .coordinate(37.5, 127.0))
        let json = String(data: try mixnavutsEncoder.encode(request), encoding: .utf8)
        XCTAssertEqual(json, #"{"destination":{"lat":37.5,"lon":127},"k":4,"mode":"balanced","origin":{"place":"시청"}}"#)
    }

    func testTurnsAndEndpoints() {
        XCTAssertEqual(Turn.of(type: "turn", modifier: "left"), .left)
        XCTAssertEqual(Turn.of(type: "ramp_on", modifier: "right"), .rampRight)
        XCTAssertEqual(Turn.of(type: "ramp_off", modifier: "slight_left"), .exitLeft)
        XCTAssertEqual(Turn.of(type: "arrive", modifier: "straight"), .arrive)
        XCTAssertEqual(Place(name: "시청", lat: 37, lon: 126).endpoint, .place("시청"))
        XCTAssertEqual(Place(name: "서울역", lat: 37.55, lon: 126.97, source: "kakao").endpoint, .coordinate(37.55, 126.97))
    }
}

final class TrackerTests: XCTestCase {
    func testFollowsSimulatedDriveToArrival() throws {
        let route = try motorwayRoute()
        let sim = RouteSimulator(route: route, startEpoch: route.depart)
        let tracker = RouteTracker(route: route)
        var lastAlong = -1.0
        var seen = Set<Int>()
        var t = 0.0
        while t <= sim.durationS {
            let progress = tracker.update(sim.fix(at: t))
            XCTAssertGreaterThanOrEqual(progress.alongM, lastAlong - 0.5)
            XCTAssertNotEqual(progress.state, .offRoute)
            lastAlong = progress.alongM
            if let next = progress.nextManeuver { seen.insert(next.pointIndex) }
            t += 2
        }
        XCTAssertEqual(tracker.update(sim.fix(at: sim.durationS)).state, .arrived)
        XCTAssertEqual(seen.count, route.maneuvers.filter { $0.type != "depart" }.count)
    }

    func testRemainingTimeFollowsPrediction() throws {
        let route = try motorwayRoute()
        let sim = RouteSimulator(route: route, startEpoch: route.depart)
        let progress = RouteTracker(route: route).update(sim.fix(at: route.durationS / 2))
        XCTAssertEqual(progress.remainingS, route.durationS / 2, accuracy: 2)
        XCTAssertEqual(progress.eta, route.arrival, accuracy: 2)
        let toManeuver = try XCTUnwrap(progress.timeToManeuverS)
        XCTAssertTrue((0...progress.remainingS).contains(toManeuver))
    }

    func testDetectsLeavingTheRoute() throws {
        let route = try motorwayRoute()
        let sim = RouteSimulator(route: route, startEpoch: route.depart, detourAtM: 2_000)
        let tracker = RouteTracker(route: route)
        let states = stride(from: 0.0, through: 900, by: 5).map { tracker.update(sim.fix(at: $0)).state }
        let firstOff = try XCTUnwrap(states.firstIndex(of: .offRoute))
        XCTAssertGreaterThan(states[..<firstOff].filter { $0 == .onRoute }.count, 3)
    }

    func testSingleBadFixIsTolerated() throws {
        let route = try motorwayRoute()
        let tracker = RouteTracker(route: route)
        let start = route.points[0]
        _ = tracker.update(Fix(time: route.depart, lat: start.lat, lon: start.lon))
        XCTAssertEqual(tracker.update(Fix(time: route.depart + 1, lat: start.lat + 0.01, lon: start.lon)).state, .onRoute)
    }
}

final class HudTests: XCTestCase {
    func testFormatting() {
        XCTAssertEqual(Format.distance(33), "35 m")
        XCTAssertEqual(Format.distance(348), "350 m")
        XCTAssertEqual(Format.distance(1_234), "1.2 km")
        XCTAssertEqual(Format.distance(22_600), "23 km")
        XCTAssertEqual(Format.duration(27 * 60 + 10), "27분")
        XCTAssertEqual(Format.duration(65 * 60), "1시간 5분")
        XCTAssertEqual(Format.clock(1_792_537_800, timeZone: kst), "08:10")
        XCTAssertEqual(Format.won(1_860), "1,860원")
    }

    func testPaceNotes() {
        let curve = Curve(startM: 1_000, endM: 2_000, direction: "right", severity: 0.85)
        XCTAssertEqual(Format.roadAhead(curve, distanceM: 400), "우측 급커브 · 400 m 앞")
        XCTAssertEqual(Format.roadAhead(curve, distanceM: 0), "우측 급커브 주행 중")
        XCTAssertNil(Format.roadAhead(curve, distanceM: 5_000))
    }

    func testPrefersVehicleSpeedAndFlagsSpeeding() throws {
        let route = try motorwayRoute()
        let fix = RouteSimulator(route: route, startEpoch: route.depart).fix(at: 60)
        let progress = RouteTracker(route: route).update(fix)
        XCTAssertEqual(Hud.build(progress: progress, fix: fix, vehicleSpeedMps: nil, timeZone: kst).speedSource, .gnss)
        let fast = Hud.build(progress: progress, fix: fix, vehicleSpeedMps: Double(progress.segment.speedLimitKmh + 20) / 3.6, timeZone: kst)
        XCTAssertEqual(fast.speedSource, .vehicle)
        XCTAssertTrue(fast.overLimit)
        XCTAssertNotNil(fast.maneuverText)
    }
}

final class LaneAndAlertTests: XCTestCase {
    func testFixtureCarriesLanesAndAlerts() throws {
        let route = try motorwayRoute()
        XCTAssertTrue(route.maneuvers.contains { $0.lanes != nil })
        XCTAssertTrue(route.alerts.contains { $0.type == "speed_camera" && $0.speedLimitKmh == 100 })
    }

    func testLanesShownNearTheManeuverOnly() throws {
        let route = try motorwayRoute()
        let guided = try XCTUnwrap(route.maneuvers.first { $0.lanes != nil })
        let tracker = RouteTracker(route: route)
        let sim = RouteSimulator(route: route, startEpoch: route.depart)
        var shownNear = false, shownFar = false
        var t = 0.0
        while t < route.durationS {
            let fix = sim.fix(at: t)
            let progress = tracker.update(fix)
            let hud = Hud.build(progress: progress, fix: fix, vehicleSpeedMps: nil, timeZone: kst)
            if progress.nextManeuver == guided, let lanes = hud.lanes {
                if progress.distanceToManeuverM! <= Hud.lanesWithinM { shownNear = true } else { shownFar = true }
                XCTAssertEqual(lanes.count, guided.lanes!.count)
                XCTAssertEqual(lanes.indices.filter { lanes[$0] }.map { $0 + 1 }, guided.lanes!.recommended)
            }
            t += 3
        }
        XCTAssertTrue(shownNear)
        XCTAssertFalse(shownFar)
    }

    func testAlertText() {
        XCTAssertEqual(Format.alert(RouteAlert(type: "speed_bump", distanceM: 0, label: "과속방지턱"), distanceM: 150), "과속방지턱 · 150 m 앞")
        XCTAssertNil(Format.alert(RouteAlert(type: "speed_bump", distanceM: 0, label: "과속방지턱"), distanceM: 400))
        XCTAssertEqual(Format.alert(RouteAlert(type: "speed_camera", distanceM: 0, label: "과속 단속 100"), distanceM: 2), "과속 단속 100")
    }
}

final class SessionTests: XCTestCase {
    final class FakeAPI: RoutesAPI, @unchecked Sendable {
        let reply: RouteOption?
        var requests: [RouteRequest] = []
        init(reply: RouteOption?) { self.reply = reply }
        func routes(_ request: RouteRequest) async throws -> RoutesResponse {
            requests.append(request)
            guard let reply else { throw APIError(status: 503, message: "engine down") }
            return RoutesResponse(routes: [reply])
        }
    }

    func testReroutesOnceWhenOffRoute() async throws {
        let route = try motorwayRoute()
        let replacement = try XCTUnwrap(loadRoutes().routes.first { $0.id != route.id })
        let api = FakeAPI(reply: replacement)
        let session = NavigationSession(api: api, route: route, destination: .place("동부산업단지"), mode: "balanced", timeZone: kst)
        let sim = RouteSimulator(route: route, startEpoch: route.depart, detourAtM: 2_000)
        var rerouted = 0
        for t in stride(from: 0.0, through: 600, by: 5) {
            if await session.onFix(sim.fix(at: t)).rerouted { rerouted += 1; break }
        }
        XCTAssertEqual(rerouted, 1)
        XCTAssertEqual(session.route.id, replacement.id)
        XCTAssertEqual(api.requests.count, 1)
        XCTAssertNotNil(api.requests[0].origin.lat)
        XCTAssertEqual(api.requests[0].destination.place, "동부산업단지")
        XCTAssertEqual(api.requests[0].k, 1)
    }

    func testReportsRerouteFailure() async throws {
        let route = try motorwayRoute()
        let session = NavigationSession(api: FakeAPI(reply: nil), route: route, destination: .place("동부산업단지"), mode: "balanced")
        let sim = RouteSimulator(route: route, startEpoch: route.depart, detourAtM: 1_000)
        var errors: [String] = []
        for t in stride(from: 0.0, through: 600, by: 5) {
            if let error = await session.onFix(sim.fix(at: t)).rerouteError { errors.append(error) }
        }
        XCTAssertEqual(errors.first, "engine down")
        XCTAssertEqual(session.route.id, route.id)
    }
}
