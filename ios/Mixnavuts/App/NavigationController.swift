import Foundation
import MixnavutsKit

/// App state and actions. The phone UI and CarPlay observe it and call these methods;
/// neither talks to the engine directly. Mirrors android NavigationController.kt.
@MainActor
final class NavigationController: ObservableObject {
    static let shared = NavigationController(api: MixnavutsAPI(baseURL: AppConfig.apiBaseURL))

    @Published private(set) var places: [Place] = []
    @Published private(set) var synthetic = true
    @Published var origin: Place?
    @Published var originIsCurrentLocation = false
    @Published var destination: Place?
    @Published private(set) var searchResults: [Place] = []
    @Published var mode = "balanced"
    @Published private(set) var plan: RoutesResponse?
    @Published var selectedIndex = 0
    @Published private(set) var loading = false
    @Published var errorMessage: String?
    @Published var simulate = true
    @Published var simulationSpeed = 1.0
    @Published private(set) var navigating = false
    @Published private(set) var update: NavUpdate?

    let location = LocationProvider()
    private let api: MixnavutsAPI
    private var session: NavigationSession?
    private var driveTask: Task<Void, Never>?

    struct ModeOption: Identifiable {
        let id: String
        let label: String
    }

    static let modes = [
        ModeOption(id: "balanced", label: "추천"),
        ModeOption(id: "fastest", label: "최단시간"),
        ModeOption(id: "economy", label: "경제"),
        ModeOption(id: "highway", label: "고속도로"),
        ModeOption(id: "scenic", label: "와인딩"),
    ]

    init(api: MixnavutsAPI) {
        self.api = api
    }

    var selectedRoute: RouteOption? {
        guard let routes = plan?.routes, routes.indices.contains(selectedIndex) else { return nil }
        return routes[selectedIndex]
    }

    func loadPlaces() async {
        guard places.isEmpty else { return }
        await run {
            let response = try await api.places()
            places = response.places
            synthetic = response.synthetic
            if origin == nil, response.synthetic { origin = response.places.first }
            if !response.synthetic { originIsCurrentLocation = true }
        }
    }

    func setOrigin(_ place: Place) {
        origin = place
        originIsCurrentLocation = false
        plan = nil
    }

    func useCurrentLocationAsOrigin() {
        location.requestPermission()
        originIsCurrentLocation = true
        plan = nil
    }

    func setDestination(_ place: Place) {
        destination = place
        searchResults = []
        plan = nil
    }

    func search(_ query: String) async {
        await run {
            let near = location.lastFix.map { (lat: $0.lat, lon: $0.lon) }
            let response = try await api.search(query, near: near)
            searchResults = response.results
            if response.results.isEmpty { errorMessage = "검색 결과가 없습니다" }
        }
    }

    func planRoutes() async {
        guard let destination else { errorMessage = "목적지를 선택하세요"; return }
        let start: Endpoint
        if originIsCurrentLocation {
            guard let here = location.lastFix else { errorMessage = "현재 위치를 아직 모릅니다"; return }
            start = .coordinate(here.lat, here.lon)
        } else {
            guard let origin else { errorMessage = "출발지를 선택하세요"; return }
            start = origin.endpoint
        }
        loading = true
        plan = nil
        await run {
            let request = RouteRequest(origin: start, destination: destination.endpoint, depart: Date().timeIntervalSince1970, mode: mode, k: 4)
            plan = try await api.routes(request)
            selectedIndex = 0
        }
        loading = false
    }

    func start(index: Int? = nil) {
        let index = index ?? selectedIndex
        guard let routes = plan?.routes, routes.indices.contains(index), let destination else { return }
        stopDriving()
        let route = routes[index]
        let nav = NavigationSession(api: api, route: route, destination: destination.endpoint, mode: mode)
        session = nav
        selectedIndex = index
        update = nil
        navigating = true
        let fixes = simulate ? Self.simulatedFixes(route: route, speed: simulationSpeed) : location.fixes()
        driveTask = Task { [weak self] in
            for await fix in fixes {
                guard !Task.isCancelled else { break }
                let next = await nav.onFix(fix)
                self?.update = next
            }
        }
    }

    /// CarPlay and the phone both stop guidance through here.
    func stop() {
        stopDriving()
        navigating = false
        update = nil
    }

    private func stopDriving() {
        driveTask?.cancel()
        driveTask = nil
        session = nil
        location.stop()
    }

    private func run(_ work: () async throws -> Void) async {
        do {
            errorMessage = nil
            try await work()
        } catch let error as APIError {
            errorMessage = error.message
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private static func simulatedFixes(route: RouteOption, speed: Double) -> AsyncStream<Fix> {
        AsyncStream { continuation in
            let task = Task {
                let simulator = RouteSimulator(route: route, startEpoch: Date().timeIntervalSince1970)
                var t = 0.0
                while t < simulator.durationS && !Task.isCancelled {
                    continuation.yield(simulator.fix(at: t))
                    try? await Task.sleep(nanoseconds: 1_000_000_000)
                    t += speed
                }
                continuation.yield(simulator.fix(at: simulator.durationS))
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }
}
