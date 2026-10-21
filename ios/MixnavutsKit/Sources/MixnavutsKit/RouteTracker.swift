import Foundation

/// A position report from GNSS or the simulator. `time` is epoch seconds.
public struct Fix: Sendable, Equatable {
    public var time: Double
    public var lat: Double
    public var lon: Double
    public var speedMps: Double?
    public var accuracyM: Double?
    public var bearingDeg: Double?

    public init(time: Double, lat: Double, lon: Double, speedMps: Double? = nil, accuracyM: Double? = nil, bearingDeg: Double? = nil) {
        self.time = time
        self.lat = lat
        self.lon = lon
        self.speedMps = speedMps
        self.accuracyM = accuracyM
        self.bearingDeg = bearingDeg
    }
}

public enum GuidanceState: Sendable { case onRoute, offRoute, arrived }

public struct Progress: Sendable {
    public var state: GuidanceState
    public var alongM: Double
    public var offsetM: Double
    public var remainingM: Double
    public var remainingS: Double
    public var eta: Double
    public var segment: Segment
    public var nextManeuver: Maneuver?
    public var distanceToManeuverM: Double?
    public var timeToManeuverS: Double?
    public var followingManeuver: Maneuver?
    public var nextCurve: Curve?
    public var distanceToCurveM: Double?
    /// Next camera or speed bump ahead (traffic lights are left to the map).
    public var nextAlert: RouteAlert?
    public var distanceToAlertM: Double?
    public var snappedLat: Double
    public var snappedLon: Double
}

/// Matches fixes to the route and works out what is next. Same rules as android/core RouteTracker.kt:
/// matching looks a little behind and well ahead of the last match, and `offRouteFixes`
/// consecutive fixes further than max(offRouteM, 1.5 × accuracy) report `.offRoute`.
public final class RouteTracker {
    public let route: RouteOption
    private let points: [RoutePoint]
    private let xs: [Double]
    private let ys: [Double]
    private let segmentOfPiece: [Int]
    private let total: Double
    private let offRouteM: Double
    private let offRouteFixes: Int
    private let arrivalM: Double
    private let projection: LocalProjection

    private var piece = -1
    private var along = 0.0
    private var misses = 0
    private var arrived = false

    public init(route: RouteOption, offRouteM: Double = 50, offRouteFixes: Int = 3, arrivalM: Double = 25) {
        self.route = route
        self.offRouteM = offRouteM
        self.offRouteFixes = offRouteFixes
        self.arrivalM = arrivalM
        let pts = route.points
        let proj = LocalProjection(lat0: pts[0].lat, lon0: pts[0].lon)
        var owner = [Int](repeating: 0, count: max(1, pts.count - 1))
        for (s, segment) in route.segments.enumerated() {
            for i in segment.startIndex..<segment.endIndex { owner[i] = s }
        }
        points = pts
        projection = proj
        xs = pts.map { proj.x($0.lon) }
        ys = pts.map { proj.y($0.lat) }
        segmentOfPiece = owner
        total = pts[pts.count - 1].distanceM
    }

    public func update(_ fix: Fix) -> Progress {
        let px = projection.x(fix.lon), py = projection.y(fix.lat)
        let range: ClosedRange<Int> = piece < 0
            ? 0...(points.count - 2)
            : max(0, piece - 3)...min(points.count - 2, piece + 40)
        var bestPiece = 0, bestT = 0.0, bestD = Double.greatestFiniteMagnitude
        for i in range {
            let (t, d) = projectOnSegment(px: px, py: py, ax: xs[i], ay: ys[i], bx: xs[i + 1], by: ys[i + 1])
            if d < bestD - 1e-9 {
                bestPiece = i
                bestT = t
                bestD = d
            }
        }
        let limit = max(offRouteM, 1.5 * (fix.accuracyM ?? 0))
        if bestD <= limit {
            misses = 0
            piece = bestPiece
            along = points[bestPiece].distanceM + bestT * (points[bestPiece + 1].distanceM - points[bestPiece].distanceM)
        } else {
            misses += 1
            if piece < 0 { piece = bestPiece }
        }
        if total - along <= arrivalM { arrived = true }
        let state: GuidanceState = arrived ? .arrived : (misses >= offRouteFixes ? .offRoute : .onRoute)
        return progress(at: fix, state: state, offset: bestD)
    }

    /// Predicted seconds from departure until the route reaches `distanceM`.
    public func predictedElapsed(at distanceM: Double) -> Double {
        let segment = route.segments.last { points[$0.startIndex].distanceM <= distanceM } ?? route.segments[0]
        let start = points[segment.startIndex].distanceM
        let end = points[segment.endIndex].distanceM
        let fraction = end > start ? min(1, max(0, (distanceM - start) / (end - start))) : 1
        return segment.offsetS + fraction * segment.durationS
    }

    private func progress(at fix: Fix, state: GuidanceState, offset: Double) -> Progress {
        let current = min(max(piece, 0), segmentOfPiece.count - 1)
        let segment = route.segments[segmentOfPiece[current]]
        let elapsed = predictedElapsed(at: along)
        let remainingS = max(0, route.durationS - elapsed)
        let upcoming = route.maneuvers.filter { $0.type != "depart" && $0.distanceM > along + 1 }
        let next = upcoming.first
        let curve = route.curves.first { $0.endM > along }
        let alert = route.alerts.first { $0.type != "traffic_light" && $0.distanceM > along - 5 }

        let p0 = points[min(max(piece, 0), points.count - 2)]
        let p1 = points[min(max(piece + 1, 1), points.count - 1)]
        let pieceLen = p1.distanceM - p0.distanceM
        let t = pieceLen > 0 ? min(1, max(0, (along - p0.distanceM) / pieceLen)) : 0
        return Progress(
            state: state,
            alongM: along,
            offsetM: offset,
            remainingM: max(0, total - along),
            remainingS: remainingS,
            eta: fix.time + remainingS,
            segment: segment,
            nextManeuver: next,
            distanceToManeuverM: next.map { $0.distanceM - along },
            timeToManeuverS: next.map { max(0, predictedElapsed(at: $0.distanceM) - elapsed) },
            followingManeuver: upcoming.count > 1 ? upcoming[1] : nil,
            nextCurve: curve,
            distanceToCurveM: curve.map { max(0, $0.startM - along) },
            nextAlert: alert,
            distanceToAlertM: alert.map { max(0, $0.distanceM - along) },
            snappedLat: p0.lat + t * (p1.lat - p0.lat),
            snappedLon: p0.lon + t * (p1.lon - p0.lon)
        )
    }
}
