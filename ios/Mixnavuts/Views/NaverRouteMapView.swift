import MixnavutsKit
import SwiftUI

#if canImport(NMapsMap)
import NMapsMap

/// 네이버 지도 SDK setup. The client ID comes from 네이버 클라우드 플랫폼 (Maps · Mobile Dynamic Map);
/// put `NAVER_MAP_CLIENT_ID = …` in Config/Local.xcconfig.
/// Newer SDK releases moved to NCP key-ID authentication (`NMFAuthManager.shared().ncpKeyId`);
/// switch the line below when upgrading the package.
enum NaverMapSetup {
    private(set) static var enabled = false

    static func configure(clientId: String) {
        guard !clientId.isEmpty else { return }
        NMFAuthManager.shared().clientId = clientId
        enabled = true
    }
}

struct NaverRouteMapView: UIViewRepresentable {
    let route: RouteOption?
    let position: (lat: Double, lon: Double)?
    let bearing: Double?
    let follow: Bool

    final class Coordinator {
        var routeId: String?
        let path = NMFPath()
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> NMFMapView { NMFMapView(frame: .zero) }

    func updateUIView(_ mapView: NMFMapView, context: Context) {
        let coordinator = context.coordinator
        if coordinator.routeId != route?.id {
            coordinator.routeId = route?.id
            coordinator.path.mapView = nil
            if let route, route.points.count >= 2 {
                let points = route.points.map { NMGLatLng(lat: $0.lat, lng: $0.lon) }
                coordinator.path.path = NMGLineString(points: points)
                coordinator.path.color = .systemBlue
                coordinator.path.width = 8
                coordinator.path.mapView = mapView
                if !follow { mapView.moveCamera(NMFCameraUpdate(fit: NMGLatLngBounds(latLngs: points), padding: 40)) }
            }
        }
        if let position {
            let here = NMGLatLng(lat: position.lat, lng: position.lon)
            mapView.locationOverlay.hidden = false
            mapView.locationOverlay.location = here
            if let bearing { mapView.locationOverlay.heading = bearing }
            if follow { mapView.moveCamera(NMFCameraUpdate(scrollTo: here)) }
        }
    }
}

#else

/// Without the NMapsMap package the app uses Apple MapKit everywhere.
enum NaverMapSetup {
    static let enabled = false
    static func configure(clientId: String) {}
}

struct NaverRouteMapView: View {
    let route: RouteOption?
    let position: (lat: Double, lon: Double)?
    let bearing: Double?
    let follow: Bool

    var body: some View {
        MapKitRouteView(route: route, position: position, bearing: bearing, follow: follow)
    }
}

#endif
