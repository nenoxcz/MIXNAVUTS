import Foundation

/// Drives a route at its predicted speeds, for demos and for testing guidance and CarPlay
/// without a car. With `detourAtM` the car drifts sideways off the route after that distance.
public struct RouteSimulator: Sendable {
    public let route: RouteOption
    public let startEpoch: Double
    public let detourAtM: Double?

    public var durationS: Double { route.durationS }

    public init(route: RouteOption, startEpoch: Double, detourAtM: Double? = nil) {
        self.route = route
        self.startEpoch = startEpoch
        self.detourAtM = detourAtM
    }

    public func fix(at elapsedS: Double) -> Fix {
        let points = route.points
        let t = min(max(elapsedS, 0), route.durationS)
        let segment = route.segments.last { $0.offsetS <= t } ?? route.segments[0]
        let fraction = segment.durationS > 0 ? min(1, max(0, (t - segment.offsetS) / segment.durationS)) : 1
        let start = points[segment.startIndex].distanceM
        let end = points[segment.endIndex].distanceM
        let along = start + fraction * (end - start)

        var i = segment.startIndex
        while i < segment.endIndex - 1 && points[i + 1].distanceM < along { i += 1 }
        let a = points[i], b = points[i + 1]
        let f = b.distanceM > a.distanceM ? min(1, max(0, (along - a.distanceM) / (b.distanceM - a.distanceM))) : 0
        var lat = a.lat + f * (b.lat - a.lat)
        var lon = a.lon + f * (b.lon - a.lon)

        let projection = LocalProjection(lat0: a.lat, lon0: a.lon)
        let heading = atan2(projection.y(b.lat), projection.x(b.lon))
        let drift = detourAtM.map { max(0, along - $0) } ?? 0
        if drift > 0 { // move to the right of the direction of travel
            lat = projection.lat(projection.y(lat) - cos(heading) * drift)
            lon = projection.lon(projection.x(lon) + sin(heading) * drift)
        }
        let speed = segment.durationS > 0 ? segment.lengthM / segment.durationS : 0
        let bearing = (90 - heading * 180 / .pi + 360).truncatingRemainder(dividingBy: 360)
        return Fix(time: startEpoch + t, lat: lat, lon: lon, speedMps: speed, accuracyM: 5, bearingDeg: bearing)
    }
}
