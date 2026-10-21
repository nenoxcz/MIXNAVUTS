import CoreLocation
import MixnavutsKit

/// GNSS fixes from Core Location. Speed and course are reported only when valid.
final class LocationProvider: NSObject, CLLocationManagerDelegate {
    private let manager = CLLocationManager()
    private var continuation: AsyncStream<Fix>.Continuation?

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBestForNavigation
        manager.activityType = .automotiveNavigation
    }

    var authorized: Bool {
        manager.authorizationStatus == .authorizedWhenInUse || manager.authorizationStatus == .authorizedAlways
    }

    var lastFix: Fix? { manager.location?.fix }

    func requestPermission() {
        if manager.authorizationStatus == .notDetermined { manager.requestWhenInUseAuthorization() }
    }

    func fixes() -> AsyncStream<Fix> {
        requestPermission()
        return AsyncStream { continuation in
            self.continuation = continuation
            manager.allowsBackgroundLocationUpdates = true // needs UIBackgroundModes: location
            manager.showsBackgroundLocationIndicator = true
            manager.startUpdatingLocation()
        }
    }

    func stop() {
        manager.stopUpdatingLocation()
        continuation?.finish()
        continuation = nil
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        for location in locations { continuation?.yield(location.fix) }
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {}
}

extension CLLocation {
    var fix: Fix {
        Fix(
            time: timestamp.timeIntervalSince1970,
            lat: coordinate.latitude,
            lon: coordinate.longitude,
            speedMps: speed >= 0 ? speed : nil,
            accuracyM: horizontalAccuracy >= 0 ? horizontalAccuracy : nil,
            bearingDeg: course >= 0 ? course : nil
        )
    }
}
