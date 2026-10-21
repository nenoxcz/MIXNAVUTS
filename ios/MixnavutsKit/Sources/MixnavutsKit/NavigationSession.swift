import Foundation

public protocol RoutesAPI: Sendable {
    func routes(_ request: RouteRequest) async throws -> RoutesResponse
}

public struct NavUpdate: Sendable {
    public var route: RouteOption
    public var progress: Progress
    public var hud: HudState
    public var fix: Fix
    public var rerouted: Bool
    public var rerouteError: String?
}

/// One guided trip: feeds fixes to the tracker, asks the engine for a new route when the
/// driver leaves the current one, and builds the HUD state. Call `onFix` from one task at a time.
public final class NavigationSession {
    public private(set) var route: RouteOption
    public var vehicleSpeedMps: Double?

    private let api: RoutesAPI
    private let destination: Endpoint
    private let mode: String
    private let timeZone: TimeZone
    private let rerouteCooldownS: Double
    private var tracker: RouteTracker
    private var lastRerouteAt = -Double.infinity

    public init(api: RoutesAPI, route: RouteOption, destination: Endpoint, mode: String,
                timeZone: TimeZone = .current, rerouteCooldownS: Double = 15) {
        self.api = api
        self.route = route
        self.destination = destination
        self.mode = mode
        self.timeZone = timeZone
        self.rerouteCooldownS = rerouteCooldownS
        tracker = RouteTracker(route: route)
    }

    public func onFix(_ fix: Fix) async -> NavUpdate {
        var progress = tracker.update(fix)
        var rerouted = false
        var failure: String?
        if progress.state == .offRoute && fix.time - lastRerouteAt >= rerouteCooldownS {
            lastRerouteAt = fix.time
            do {
                let request = RouteRequest(origin: .coordinate(fix.lat, fix.lon), destination: destination, depart: fix.time, mode: mode, k: 1)
                if let replacement = try await api.routes(request).routes.first {
                    route = replacement
                    tracker = RouteTracker(route: replacement)
                    progress = tracker.update(fix)
                    rerouted = true
                }
            } catch {
                failure = (error as? APIError)?.message ?? error.localizedDescription
            }
        }
        let hud = Hud.build(progress: progress, fix: fix, vehicleSpeedMps: vehicleSpeedMps, timeZone: timeZone)
        return NavUpdate(route: route, progress: progress, hud: hud, fix: fix, rerouted: rerouted, rerouteError: failure)
    }
}
