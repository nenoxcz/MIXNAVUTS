import MapKit
import MixnavutsKit
import SwiftUI
import UIKit

/// What the phone screen and the CarPlay window need from a map.
protocol RouteMapDisplay: UIViewController {
    func show(route: RouteOption?, fit: Bool)
    func moveCar(lat: Double, lon: Double, bearing: Double?, follow: Bool)
}

enum RouteMapFactory {
    /// The engine's own map through MapLibre when the package is linked and a style URL is set;
    /// Apple MapKit otherwise.
    static func make() -> RouteMapDisplay {
        #if canImport(MapLibre)
        if let style = AppConfig.mapStyleURL { return MapLibreRouteViewController(styleURL: style) }
        #endif
        return RouteMapViewController()
    }
}

struct RouteMapView: UIViewControllerRepresentable {
    let route: RouteOption?
    let position: (lat: Double, lon: Double)?
    let bearing: Double?
    let follow: Bool

    func makeUIViewController(context: Context) -> UIViewController { RouteMapFactory.make() }

    func updateUIViewController(_ controller: UIViewController, context: Context) {
        guard let map = controller as? RouteMapDisplay else { return }
        map.show(route: route, fit: !follow)
        if let position { map.moveCar(lat: position.lat, lon: position.lon, bearing: bearing, follow: follow) }
    }
}

/// MapKit view with the route line and a car marker. Shared by the phone and the CarPlay window.
final class RouteMapViewController: UIViewController, MKMapViewDelegate, RouteMapDisplay {
    let mapView = MKMapView()
    private var routeId: String?
    private let car = MKPointAnnotation()

    override func loadView() {
        mapView.delegate = self
        mapView.showsCompass = false
        mapView.pointOfInterestFilter = .excludingAll
        view = mapView
    }

    func show(route: RouteOption?, fit: Bool) {
        guard route?.id != routeId else { return }
        routeId = route?.id
        mapView.removeOverlays(mapView.overlays)
        guard let route, route.points.count >= 2 else { return }
        var coordinates = route.points.map { CLLocationCoordinate2D(latitude: $0.lat, longitude: $0.lon) }
        let line = MKPolyline(coordinates: &coordinates, count: coordinates.count)
        mapView.addOverlay(line)
        if fit {
            mapView.setVisibleMapRect(line.boundingMapRect, edgePadding: UIEdgeInsets(top: 40, left: 40, bottom: 40, right: 40), animated: false)
        }
    }

    func moveCar(lat: Double, lon: Double, bearing: Double?, follow: Bool) {
        let here = CLLocationCoordinate2D(latitude: lat, longitude: lon)
        car.coordinate = here
        if !mapView.annotations.contains(where: { $0 === car }) { mapView.addAnnotation(car) }
        if follow {
            let camera = MKMapCamera(lookingAtCenter: here, fromDistance: 1_200, pitch: 0, heading: bearing ?? mapView.camera.heading)
            mapView.setCamera(camera, animated: true)
        }
    }

    func mapView(_ mapView: MKMapView, rendererFor overlay: MKOverlay) -> MKOverlayRenderer {
        guard let line = overlay as? MKPolyline else { return MKOverlayRenderer(overlay: overlay) }
        let renderer = MKPolylineRenderer(polyline: line)
        renderer.strokeColor = .systemBlue
        renderer.lineWidth = 6
        return renderer
    }
}
