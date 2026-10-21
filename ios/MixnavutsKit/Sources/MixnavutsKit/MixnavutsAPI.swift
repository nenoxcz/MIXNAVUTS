import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public struct APIError: Error, Sendable {
    public var status: Int
    public var message: String
}

/// Client for the MIXNAVUTS Engine API (docs/API.md).
public struct MixnavutsAPI: RoutesAPI {
    public let baseURL: URL
    private let session: URLSession

    public init(baseURL: URL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
    }

    public func places() async throws -> PlacesResponse {
        try await get("v1/places")
    }

    public func search(_ query: String, near: (lat: Double, lon: Double)? = nil) async throws -> SearchResponse {
        var items = [URLQueryItem(name: "q", value: query)]
        if let near {
            items += [URLQueryItem(name: "lat", value: "\(near.lat)"), URLQueryItem(name: "lon", value: "\(near.lon)")]
        }
        return try await get("v1/search", query: items)
    }

    public func routes(_ request: RouteRequest) async throws -> RoutesResponse {
        var urlRequest = URLRequest(url: baseURL.appendingPathComponent("v1/routes"))
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = try mixnavutsEncoder.encode(request)
        return try await send(urlRequest)
    }

    private func get<T: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> T {
        var components = URLComponents(url: baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query }
        return try await send(URLRequest(url: components.url!))
    }

    private func send<T: Decodable>(_ request: URLRequest) async throws -> T {
        var request = request
        request.timeoutInterval = 15
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            let message = (try? JSONDecoder().decode([String: String].self, from: data))?["error"] ?? "HTTP \(status)"
            throw APIError(status: status, message: message)
        }
        return try mixnavutsDecoder.decode(T.self, from: data)
    }
}
