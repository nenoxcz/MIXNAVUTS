import Foundation

public enum SpeedSource: Sendable { case vehicle, gnss }

/// Everything a HUD, cluster or phone screen shows, already decided and formatted.
/// Screens only lay this out; the look is theirs.
public struct HudState: Sendable {
    public var state: GuidanceState
    public var speedKmh: Int?
    public var speedSource: SpeedSource?
    public var limitKmh: Int?
    public var overLimit: Bool
    public var turn: Turn?
    public var maneuverDistance: String?
    public var maneuverText: String?
    public var thenText: String?
    public var roadAhead: String?
    public var roadName: String
    public var eta: String
    public var remainingDistance: String
    public var remainingTime: String
}

public enum Format {
    public static func distance(_ m: Double) -> String {
        if m < 50 { return "\(Int((m / 5).rounded()) * 5) m" }
        if m < 1_000 { return "\(Int((m / 10).rounded()) * 10) m" }
        if m < 10_000 { return String(format: "%.1f km", m / 1_000) }
        return "\(Int((m / 1_000).rounded())) km"
    }

    public static func duration(_ s: Double) -> String {
        let minutes = Int((s / 60).rounded())
        return minutes < 60 ? "\(minutes)분" : "\(minutes / 60)시간 \(minutes % 60)분"
    }

    public static func clock(_ epochS: Double, timeZone: TimeZone = .current) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: Date(timeIntervalSince1970: epochS))
    }

    public static func won(_ krw: Int) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.groupingSeparator = ","
        formatter.usesGroupingSeparator = true
        return (formatter.string(from: NSNumber(value: krw)) ?? "\(krw)") + "원"
    }

    /// Rally-style pace note for the next winding stretch, if it is close.
    public static func roadAhead(_ curve: Curve?, distanceM: Double?, within: Double = 1_500) -> String? {
        guard let curve, let distanceM, distanceM <= within else { return nil }
        let kind: String
        switch curve.direction {
        case "left": kind = curve.severity >= 0.7 ? "좌측 급커브" : "좌측 굽은 구간"
        case "right": kind = curve.severity >= 0.7 ? "우측 급커브" : "우측 굽은 구간"
        default: kind = "연속 굽은 길"
        }
        return distanceM < 1 ? "\(kind) 주행 중" : "\(kind) · \(distance(distanceM)) 앞"
    }
}

public enum Hud {
    public static func build(progress: Progress, fix: Fix, vehicleSpeedMps: Double?, timeZone: TimeZone = .current) -> HudState {
        let speedMps = vehicleSpeedMps ?? fix.speedMps
        let speedKmh = speedMps.map { Int(($0 * 3.6).rounded()) }
        let limit = progress.segment.speedLimitKmh > 0 ? progress.segment.speedLimitKmh : nil
        let next = progress.nextManeuver
        let text: String?
        switch progress.state {
        case .arrived: text = "목적지에 도착했습니다"
        case .offRoute: text = "경로를 벗어났습니다 · 재탐색"
        case .onRoute: text = next?.instruction
        }
        var then: String?
        if let next, let following = progress.followingManeuver, following.distanceM - next.distanceM < 300 {
            then = "이어서 \(following.instruction)"
        }
        return HudState(
            state: progress.state,
            speedKmh: speedKmh,
            speedSource: vehicleSpeedMps != nil ? .vehicle : (fix.speedMps != nil ? .gnss : nil),
            limitKmh: limit,
            overLimit: speedKmh != nil && limit != nil && speedKmh! > limit!,
            turn: next?.turn,
            maneuverDistance: progress.distanceToManeuverM.map(Format.distance),
            maneuverText: text,
            thenText: then,
            roadAhead: Format.roadAhead(progress.nextCurve, distanceM: progress.distanceToCurveM),
            roadName: progress.segment.roadName,
            eta: Format.clock(progress.eta, timeZone: timeZone),
            remainingDistance: Format.distance(progress.remainingM),
            remainingTime: Format.duration(progress.remainingS)
        )
    }
}
