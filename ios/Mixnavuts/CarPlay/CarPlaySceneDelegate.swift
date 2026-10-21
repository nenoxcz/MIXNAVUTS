import CarPlay
import Combine
import MapKit
import MixnavutsKit
import UIKit

/// CarPlay navigation: destination list → trip preview with the engine's routes → guidance.
/// The base view is the same map as the phone (the engine's own map through MapLibre, or MapKit).
/// Maneuvers go to CPNavigationSession, which is also what CarPlay shows in the instrument
/// cluster and HUD of cars that support it. Requires the CarPlay Navigation entitlement.
final class CarPlaySceneDelegate: UIResponder, CPTemplateApplicationSceneDelegate, CPMapTemplateDelegate {
    private var interfaceController: CPInterfaceController?
    private var window: CPWindow?
    private lazy var mapController: RouteMapDisplay = RouteMapFactory.make()
    private let mapTemplate = CPMapTemplate()
    private var trip: CPTrip?
    private var session: CPNavigationSession?
    private var shownManeuver: (routeId: String, pointIndex: Int)?
    private var currentManeuver: CPManeuver?
    private var cancellables = Set<AnyCancellable>()

    private var controller: NavigationController { .shared }

    // MARK: Scene

    func templateApplicationScene(_ templateApplicationScene: CPTemplateApplicationScene,
                                  didConnect interfaceController: CPInterfaceController,
                                  to window: CPWindow) {
        self.interfaceController = interfaceController
        self.window = window
        window.rootViewController = mapController
        mapTemplate.mapDelegate = self
        showIdleButtons()
        interfaceController.setRootTemplate(mapTemplate, animated: false, completion: nil)

        controller.$update
            .receive(on: RunLoop.main)
            .sink { [weak self] update in self?.render(update) }
            .store(in: &cancellables)
        controller.$navigating
            .removeDuplicates()
            .receive(on: RunLoop.main)
            .sink { [weak self] navigating in self?.navigationChanged(navigating) }
            .store(in: &cancellables)
        Task { await controller.loadPlaces() }
    }

    func templateApplicationScene(_ templateApplicationScene: CPTemplateApplicationScene,
                                  didDisconnect interfaceController: CPInterfaceController,
                                  from window: CPWindow) {
        cancellables.removeAll()
        session?.cancelTrip()
        session = nil
        self.interfaceController = nil
        self.window = nil
    }

    // MARK: Destinations and preview

    private func showIdleButtons() {
        mapTemplate.leadingNavigationBarButtons = [CPBarButton(title: "목적지") { [weak self] _ in self?.showDestinations() }]
        mapTemplate.trailingNavigationBarButtons = []
    }

    private func showDestinations() {
        let items = controller.places.prefix(CPListTemplate.maximumItemCount).map { place -> CPListItem in
            let item = CPListItem(text: place.name, detailText: place.address.isEmpty ? nil : place.address)
            item.handler = { [weak self] _, completion in
                self?.choose(place)
                completion()
            }
            return item
        }
        let list = CPListTemplate(title: "목적지", sections: [CPListSection(items: Array(items))])
        interfaceController?.pushTemplate(list, animated: true, completion: nil)
    }

    private func choose(_ place: Place) {
        controller.setDestination(place)
        interfaceController?.popToRootTemplate(animated: true, completion: nil)
        Task {
            await controller.planRoutes()
            showPreview()
        }
    }

    private func showPreview() {
        guard let plan = controller.plan, let first = plan.routes.first else { return }
        let trip = makeTrip(routes: plan.routes)
        self.trip = trip
        mapController.show(route: first, fit: true)
        let text = CPTripPreviewTextConfiguration(startButtonTitle: "안내 시작", additionalRoutesButtonTitle: "다른 경로", overviewButtonTitle: "개요")
        mapTemplate.showTripPreviews([trip], textConfiguration: text)
    }

    private func makeTrip(routes: [RouteOption]) -> CPTrip {
        let start = routes[0].points[0]
        let end = routes[0].points[routes[0].points.count - 1]
        let origin = MKMapItem(placemark: MKPlacemark(coordinate: CLLocationCoordinate2D(latitude: start.lat, longitude: start.lon)))
        let destination = MKMapItem(placemark: MKPlacemark(coordinate: CLLocationCoordinate2D(latitude: end.lat, longitude: end.lon)))
        destination.name = controller.destination?.name
        let choices = routes.map { route -> CPRouteChoice in
            let choice = CPRouteChoice(
                summaryVariants: [route.labels.joined(separator: " · ")],
                additionalInformationVariants: [route.summary],
                selectionSummaryVariants: ["\(Format.duration(route.durationS)) · \(Format.distance(route.distanceM)) · \(Format.won(route.tollKrw))"]
            )
            choice.userInfo = route.id
            return choice
        }
        return CPTrip(origin: origin, destination: destination, routeChoices: choices)
    }

    private func routeIndex(_ choice: CPRouteChoice) -> Int? {
        guard let id = choice.userInfo as? String else { return nil }
        return controller.plan?.routes.firstIndex { $0.id == id }
    }

    func mapTemplate(_ mapTemplate: CPMapTemplate, selectedPreviewFor trip: CPTrip, using routeChoice: CPRouteChoice) {
        guard let index = routeIndex(routeChoice), let route = controller.plan?.routes[index] else { return }
        controller.selectedIndex = index
        mapController.show(route: route, fit: true)
    }

    func mapTemplate(_ mapTemplate: CPMapTemplate, startedTrip trip: CPTrip, using routeChoice: CPRouteChoice) {
        mapTemplate.hideTripPreviews()
        controller.start(index: routeIndex(routeChoice))
        session = mapTemplate.startNavigationSession(for: trip)
    }

    // MARK: Guidance

    private func navigationChanged(_ navigating: Bool) {
        if navigating {
            mapTemplate.leadingNavigationBarButtons = []
            mapTemplate.trailingNavigationBarButtons = [CPBarButton(title: "종료") { [weak self] _ in self?.controller.stop() }]
            if session == nil, let route = controller.selectedRoute { // guidance was started on the phone
                let trip = makeTrip(routes: [route])
                self.trip = trip
                session = mapTemplate.startNavigationSession(for: trip)
            }
        } else {
            session?.cancelTrip()
            session = nil
            shownManeuver = nil
            currentManeuver = nil
            showIdleButtons()
        }
    }

    private func render(_ update: NavUpdate?) {
        guard let update else { return }
        mapController.show(route: update.route, fit: false)
        mapController.moveCar(lat: update.progress.snappedLat, lon: update.progress.snappedLon, bearing: update.fix.bearingDeg, follow: true)
        guard let session else { return }
        let progress = update.progress

        switch progress.state {
        case .arrived:
            session.finishTrip()
            self.session = nil
            return
        case .offRoute:
            session.pauseTrip(for: .rerouting, description: "경로 재탐색 중")
            return
        case .onRoute:
            break
        }

        if let next = progress.nextManeuver {
            let distance = Measurement(value: progress.distanceToManeuverM ?? 0, unit: UnitLength.meters)
            let estimates = CPTravelEstimates(distanceRemaining: distance, timeRemaining: progress.timeToManeuverS ?? 0)
            if shownManeuver?.routeId != update.route.id || shownManeuver?.pointIndex != next.pointIndex {
                let maneuver = cpManeuver(next, estimates: estimates)
                var upcoming = [maneuver]
                if let following = progress.followingManeuver { upcoming.append(cpManeuver(following, estimates: nil)) }
                session.upcomingManeuvers = upcoming
                shownManeuver = (update.route.id, next.pointIndex)
                currentManeuver = maneuver
            } else if let currentManeuver {
                session.updateEstimates(estimates, for: currentManeuver)
            }
        }
        if let trip {
            let remaining = CPTravelEstimates(
                distanceRemaining: Measurement(value: progress.remainingM / 1_000, unit: UnitLength.kilometers),
                timeRemaining: progress.remainingS
            )
            mapTemplate.update(remaining, for: trip, with: .default)
        }
    }

    private func cpManeuver(_ maneuver: Maneuver, estimates: CPTravelEstimates?) -> CPManeuver {
        let item = CPManeuver()
        item.instructionVariants = [maneuver.instruction]
        item.symbolImage = UIImage(systemName: maneuver.turn.symbolName)
        if let estimates { item.initialTravelEstimates = estimates }
        item.userInfo = maneuver.pointIndex
        return item
    }
}
