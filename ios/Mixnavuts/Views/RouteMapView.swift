import MapKit
import MixnavutsKit
import SwiftUI
import UIKit

/// The route on a map: 네이버 지도 when the NMapsMap package is linked and a client ID is
/// configured, Apple MapKit otherwise. CarPlay always uses `RouteMapViewController` (MapKit).
struct RouteMapView: View {
    let route: RouteOption?
    let position: (lat: Double, lon: Double)?
    let bearing: Double?
    let follow: Bool

    var body: some View {
        if NaverMapSetup.enabled {
            NaverRouteMapView(route: route, position: position, bearing: bearing, follow: follow)
        } else {
            MapKitRouteView(route: route, position: position, bearing: bearing, follow: follow)
        }
    }
}

struct MapKitRouteView: UIViewControllerRepresentable {
    let route: RouteOption?
    let position: (lat: Double, lon: Double)?
    let bearing: Double?
    let follow: Bool

    func makeUIViewController(context: Context) -> RouteMapViewController { RouteMapViewController() }

    func updateUIViewController(_ controller: RouteMapViewController, context: Context) {
        controller.show(route: route, fit: !follow)
        if let position { controller.moveCar(lat: position.lat, lon: position.lon, bearing: bearing, follow: follow) }
    }
}

/// MapKit view with the route line and a car marker. Shared by the phone and the CarPlay window.
final class RouteMapViewController: UIViewController, MKMapViewDelegate {
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
