#if canImport(MapLibre)
import MapLibre
import MixnavutsKit
import UIKit

/// The engine's own map (/v1/style.json: road network vector tiles, optionally on the
/// 브이월드 base map) rendered by MapLibre, with the route and the car on top.
/// Used on the phone and in the CarPlay window.
final class MapLibreRouteViewController: UIViewController, MLNMapViewDelegate, RouteMapDisplay {
    private let styleURL: URL
    private var mapView: MLNMapView!
    private var routeSource: MLNShapeSource?
    private var carSource: MLNShapeSource?
    private var routeId: String?
    private var pending: (route: RouteOption?, fit: Bool)?

    init(styleURL: URL) {
        self.styleURL = styleURL
        super.init(nibName: nil, bundle: nil)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    override func loadView() {
        mapView = MLNMapView(frame: .zero, styleURL: styleURL)
        mapView.delegate = self
        view = mapView
    }

    func mapView(_ mapView: MLNMapView, didFinishLoading style: MLNStyle) {
        let route = MLNShapeSource(identifier: "mixnavuts-route", shape: nil, options: nil)
        let car = MLNShapeSource(identifier: "mixnavuts-car", shape: nil, options: nil)
        style.addSource(route)
        style.addSource(car)

        let line = MLNLineStyleLayer(identifier: "mixnavuts-route", source: route)
        line.lineColor = NSExpression(forConstantValue: UIColor.systemBlue)
        line.lineWidth = NSExpression(forConstantValue: 7)
        line.lineCap = NSExpression(forConstantValue: "round")
        line.lineJoin = NSExpression(forConstantValue: "round")
        style.addLayer(line)

        let dot = MLNCircleStyleLayer(identifier: "mixnavuts-car", source: car)
        dot.circleRadius = NSExpression(forConstantValue: 8)
        dot.circleColor = NSExpression(forConstantValue: UIColor.black)
        dot.circleStrokeColor = NSExpression(forConstantValue: UIColor.white)
        dot.circleStrokeWidth = NSExpression(forConstantValue: 2)
        style.addLayer(dot)

        routeSource = route
        carSource = car
        if let pending {
            self.pending = nil
            show(route: pending.route, fit: pending.fit)
        }
    }

    func show(route: RouteOption?, fit: Bool) {
        guard let routeSource else {
            pending = (route, fit) // the style is still loading
            return
        }
        guard route?.id != routeId else { return }
        routeId = route?.id
        guard let route, route.points.count >= 2 else {
            routeSource.shape = nil
            return
        }
        var coordinates = route.points.map { CLLocationCoordinate2D(latitude: $0.lat, longitude: $0.lon) }
        routeSource.shape = MLNPolylineFeature(coordinates: &coordinates, count: UInt(coordinates.count))
        if fit {
            let padding = UIEdgeInsets(top: 40, left: 40, bottom: 40, right: 40)
            mapView.setVisibleCoordinates(&coordinates, count: UInt(coordinates.count), edgePadding: padding, animated: false)
        }
    }

    func moveCar(lat: Double, lon: Double, bearing: Double?, follow: Bool) {
        let here = CLLocationCoordinate2D(latitude: lat, longitude: lon)
        let point = MLNPointFeature()
        point.coordinate = here
        carSource?.shape = point
        if follow {
            let camera = MLNMapCamera(lookingAtCenter: here, altitude: 1_200, pitch: 45, heading: bearing ?? mapView.direction)
            mapView.setCamera(camera, animated: true)
        }
    }
}
#endif
