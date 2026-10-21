import Foundation

public let earthRadiusM = 6_371_008.8

public func haversineM(_ lat1: Double, _ lon1: Double, _ lat2: Double, _ lon2: Double) -> Double {
    let p1 = lat1 * .pi / 180, p2 = lat2 * .pi / 180
    let dp = p2 - p1, dl = (lon2 - lon1) * .pi / 180
    let h = sin(dp / 2) * sin(dp / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2)
    return 2 * earthRadiusM * asin(sqrt(h))
}

/// Equirectangular projection around a reference point; metres east (x) and north (y).
public struct LocalProjection: Sendable {
    let lat0: Double
    let lon0: Double
    let cosLat0: Double

    public init(lat0: Double, lon0: Double) {
        self.lat0 = lat0
        self.lon0 = lon0
        cosLat0 = cos(lat0 * .pi / 180)
    }

    public func x(_ lon: Double) -> Double { (lon - lon0) * .pi / 180 * earthRadiusM * cosLat0 }
    public func y(_ lat: Double) -> Double { (lat - lat0) * .pi / 180 * earthRadiusM }
    public func lat(_ y: Double) -> Double { lat0 + y / earthRadiusM * 180 / .pi }
    public func lon(_ x: Double) -> Double { lon0 + x / (earthRadiusM * cosLat0) * 180 / .pi }
}

/// Closest point on segment a→b to p: (fraction along the segment, distance).
func projectOnSegment(px: Double, py: Double, ax: Double, ay: Double, bx: Double, by: Double) -> (t: Double, d: Double) {
    let dx = bx - ax, dy = by - ay
    let len2 = dx * dx + dy * dy
    let t = len2 == 0 ? 0 : min(1, max(0, ((px - ax) * dx + (py - ay) * dy) / len2))
    return (t, hypot(px - (ax + t * dx), py - (ay + t * dy)))
}

/// Fits a route into a w×h box, north up (used by the plain route drawing).
public struct ScreenFit: Sendable {
    private let projection: LocalProjection
    private let minX: Double
    private let maxY: Double
    private let scale: Double
    private let offsetX: Double
    private let offsetY: Double

    public init(points: [RoutePoint], width: Double, height: Double, padding: Double) {
        projection = LocalProjection(lat0: points[0].lat, lon0: points[0].lon)
        let xs = points.map { projection.x($0.lon) }
        let ys = points.map { projection.y($0.lat) }
        minX = xs.min() ?? 0
        maxY = ys.max() ?? 0
        let spanX = max(1, (xs.max() ?? 0) - minX)
        let spanY = max(1, maxY - (ys.min() ?? 0))
        let usableW = max(1, width - 2 * padding)
        let usableH = max(1, height - 2 * padding)
        scale = min(usableW / spanX, usableH / spanY)
        offsetX = padding + (usableW - spanX * scale) / 2
        offsetY = padding + (usableH - spanY * scale) / 2
    }

    public func x(_ lat: Double, _ lon: Double) -> Double { offsetX + (projection.x(lon) - minX) * scale }
    public func y(_ lat: Double, _ lon: Double) -> Double { offsetY + (maxY - projection.y(lat)) * scale }
}
