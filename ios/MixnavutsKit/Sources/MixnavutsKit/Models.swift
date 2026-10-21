import Foundation

// API models for the MIXNAVUTS Engine (docs/API.md). Mirrors android/core Models.kt.

public struct Place: Codable, Hashable, Identifiable, Sendable {
    public var name: String
    public var lat: Double
    public var lon: Double
    public var address: String
    public var category: String
    public var source: String

    public var id: String { "\(source):\(name):\(lat),\(lon)" }

    /// Network places are sent by name; search results (e.g. 카카오) by coordinate.
    public var endpoint: Endpoint { source == "network" ? .place(name) : .coordinate(lat, lon) }

    public init(name: String, lat: Double, lon: Double, address: String = "", category: String = "", source: String = "network") {
        self.name = name
        self.lat = lat
        self.lon = lon
        self.address = address
        self.category = category
        self.source = source
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        lat = try c.decode(Double.self, forKey: .lat)
        lon = try c.decode(Double.self, forKey: .lon)
        address = try c.decodeIfPresent(String.self, forKey: .address) ?? ""
        category = try c.decodeIfPresent(String.self, forKey: .category) ?? ""
        source = try c.decodeIfPresent(String.self, forKey: .source) ?? "network"
    }
}

public struct PlacesResponse: Codable, Sendable {
    public var synthetic: Bool
    public var places: [Place]
}

public struct SearchResponse: Codable, Sendable {
    public var provider: String
    public var results: [Place]
}

/// Origin or destination: a named place of the network, or a coordinate.
public struct Endpoint: Codable, Hashable, Sendable {
    public var place: String?
    public var lat: Double?
    public var lon: Double?

    public static func place(_ name: String) -> Endpoint { Endpoint(place: name, lat: nil, lon: nil) }
    public static func coordinate(_ lat: Double, _ lon: Double) -> Endpoint { Endpoint(place: nil, lat: lat, lon: lon) }
}

public struct RouteRequest: Codable, Sendable {
    public var origin: Endpoint
    public var destination: Endpoint
    public var depart: Double?
    public var mode: String
    public var k: Int

    public init(origin: Endpoint, destination: Endpoint, depart: Double? = nil, mode: String = "balanced", k: Int = 4) {
        self.origin = origin
        self.destination = destination
        self.depart = depart
        self.mode = mode
        self.k = k
    }
}

public struct LiveInfo: Codable, Sendable {
    public var source: String
    public var asOf: Double?
    public var incidents: Int

    enum CodingKeys: String, CodingKey {
        case source, incidents
        case asOf = "as_of"
    }
}

public struct RoutesResponse: Codable, Sendable {
    public var synthetic: Bool
    public var network: String
    public var mode: String
    public var depart: Double
    public var candidates: Int
    public var candidateSources: [String: Int]
    public var live: LiveInfo
    public var routes: [RouteOption]

    enum CodingKeys: String, CodingKey {
        case synthetic, network, mode, depart, candidates, live, routes
        case candidateSources = "candidate_sources"
    }

    public init(synthetic: Bool = false, network: String = "", mode: String = "balanced", depart: Double = 0, candidates: Int = 0,
                candidateSources: [String: Int] = [:], live: LiveInfo = LiveInfo(source: "none", asOf: nil, incidents: 0),
                routes: [RouteOption]) {
        self.synthetic = synthetic
        self.network = network
        self.mode = mode
        self.depart = depart
        self.candidates = candidates
        self.candidateSources = candidateSources
        self.live = live
        self.routes = routes
    }
}

public struct RoutePoint: Hashable, Sendable {
    public var lat: Double
    public var lon: Double
    public var distanceM: Double
}

public struct RouteOption: Codable, Identifiable, Sendable {
    public var id: String
    public var labels: [String]
    public var depart: Double
    public var arrival: Double
    public var durationS: Double
    public var distanceM: Double
    public var tollKrw: Int
    public var highwayShare: Double
    public var winding: Double
    public var summary: String
    /// [lat, lon, distance along the route in metres] per vertex.
    public var geometry: [[Double]]
    public var segments: [Segment]
    public var maneuvers: [Maneuver]
    public var curves: [Curve]
    /// Cameras, traffic lights and speed bumps along the route, in driving order.
    public var alerts: [RouteAlert]

    public var points: [RoutePoint] { geometry.map { RoutePoint(lat: $0[0], lon: $0[1], distanceM: $0[2]) } }

    enum CodingKeys: String, CodingKey {
        case id, labels, depart, arrival, winding, summary, geometry, segments, maneuvers, curves, alerts
        case durationS = "duration_s"
        case distanceM = "distance_m"
        case tollKrw = "toll_krw"
        case highwayShare = "highway_share"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        labels = try c.decode([String].self, forKey: .labels)
        depart = try c.decode(Double.self, forKey: .depart)
        arrival = try c.decode(Double.self, forKey: .arrival)
        durationS = try c.decode(Double.self, forKey: .durationS)
        distanceM = try c.decode(Double.self, forKey: .distanceM)
        tollKrw = try c.decode(Int.self, forKey: .tollKrw)
        highwayShare = try c.decode(Double.self, forKey: .highwayShare)
        winding = try c.decode(Double.self, forKey: .winding)
        summary = try c.decode(String.self, forKey: .summary)
        geometry = try c.decode([[Double]].self, forKey: .geometry)
        segments = try c.decode([Segment].self, forKey: .segments)
        maneuvers = try c.decode([Maneuver].self, forKey: .maneuvers)
        curves = try c.decodeIfPresent([Curve].self, forKey: .curves) ?? []
        alerts = try c.decodeIfPresent([RouteAlert].self, forKey: .alerts) ?? []
    }
}

/// `recommended` counts from 1 = 1차로 (leftmost).
public struct LaneHint: Codable, Hashable, Sendable {
    public var count: Int
    public var recommended: [Int]
}

public struct RouteAlert: Codable, Hashable, Sendable {
    /// speed_camera, signal_camera, section_camera, traffic_light, speed_bump
    public var type: String
    public var distanceM: Double
    public var speedLimitKmh: Int?
    public var label: String
    public var note: String?

    public init(type: String, distanceM: Double, speedLimitKmh: Int? = nil, label: String, note: String? = nil) {
        self.type = type
        self.distanceM = distanceM
        self.speedLimitKmh = speedLimitKmh
        self.label = label
        self.note = note
    }

    enum CodingKeys: String, CodingKey {
        case type, label, note
        case distanceM = "distance_m"
        case speedLimitKmh = "speed_limit_kmh"
    }
}

public struct Segment: Codable, Sendable {
    public var startIndex: Int
    public var endIndex: Int
    public var lengthM: Double
    public var speedLimitKmh: Int
    public var roadName: String
    public var roadClass: String
    public var curvature: Double
    public var tollKrw: Int
    public var offsetS: Double
    public var durationS: Double
    public var linkId: String?

    enum CodingKeys: String, CodingKey {
        case curvature
        case startIndex = "start_index"
        case endIndex = "end_index"
        case lengthM = "length_m"
        case speedLimitKmh = "speed_limit_kmh"
        case roadName = "road_name"
        case roadClass = "road_class"
        case tollKrw = "toll_krw"
        case offsetS = "offset_s"
        case durationS = "duration_s"
        case linkId = "link_id"
    }
}

public struct Maneuver: Codable, Hashable, Sendable {
    public var pointIndex: Int
    public var distanceM: Double
    public var type: String
    public var modifier: String
    public var roadName: String
    public var instruction: String
    /// Which lanes to be in (from 정밀도로지도, or the usual lanes for the maneuver).
    public var lanes: LaneHint?

    public var turn: Turn { Turn.of(type: type, modifier: modifier) }

    enum CodingKeys: String, CodingKey {
        case type, modifier, instruction, lanes
        case pointIndex = "point_index"
        case distanceM = "distance_m"
        case roadName = "road_name"
    }
}

public struct Curve: Codable, Hashable, Sendable {
    public var startM: Double
    public var endM: Double
    public var direction: String
    public var severity: Double

    public init(startM: Double, endM: Double, direction: String, severity: Double) {
        self.startM = startM
        self.endM = endM
        self.direction = direction
        self.severity = severity
    }

    enum CodingKeys: String, CodingKey {
        case direction, severity
        case startM = "start_m"
        case endM = "end_m"
    }
}

/// One maneuver symbol, so the phone, CarPlay and the cluster all pick the same icon.
public enum Turn: String, Sendable, CaseIterable {
    case depart, straight, slightLeft, left, sharpLeft, slightRight, right, sharpRight, uturn
    case rampLeft, rampRight, exitLeft, exitRight, forkLeft, forkRight, arrive

    public static func of(type: String, modifier: String) -> Turn {
        let isLeft = modifier.contains("left")
        switch type {
        case "depart": return .depart
        case "arrive": return .arrive
        case "ramp_on": return isLeft ? .rampLeft : .rampRight
        case "ramp_off": return isLeft ? .exitLeft : .exitRight
        case "fork": return isLeft ? .forkLeft : .forkRight
        default:
            switch modifier {
            case "slight_left": return .slightLeft
            case "left": return .left
            case "sharp_left": return .sharpLeft
            case "slight_right": return .slightRight
            case "right": return .right
            case "sharp_right": return .sharpRight
            case "uturn": return .uturn
            default: return .straight
            }
        }
    }

    /// SF Symbol for the maneuver (placeholder art until the designed icon set exists).
    public var symbolName: String {
        switch self {
        case .depart: return "location.north.fill"
        case .straight: return "arrow.up"
        case .slightLeft, .rampLeft, .exitLeft, .forkLeft: return "arrow.up.left"
        case .left: return "arrow.turn.up.left"
        case .sharpLeft: return "arrow.turn.down.left"
        case .slightRight, .rampRight, .exitRight, .forkRight: return "arrow.up.right"
        case .right: return "arrow.turn.up.right"
        case .sharpRight: return "arrow.turn.down.right"
        case .uturn: return "arrow.uturn.down"
        case .arrive: return "mappin.and.ellipse"
        }
    }
}

public let mixnavutsDecoder = JSONDecoder()
public let mixnavutsEncoder: JSONEncoder = {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    return encoder
}()
