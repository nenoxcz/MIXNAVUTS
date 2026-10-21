import MixnavutsKit
import SwiftUI

@main
struct MixnavutsApp: App {
    @StateObject private var controller = NavigationController.shared

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(controller)
                .task { await controller.loadPlaces() }
        }
    }
}

/// Values from Info.plist, filled from Config/Mixnavuts.xcconfig (and an optional Config/Local.xcconfig).
enum AppConfig {
    static var apiBaseURL: URL {
        let text = Bundle.main.object(forInfoDictionaryKey: "MixnavutsAPIBaseURL") as? String
        return URL(string: text ?? "") ?? URL(string: "http://localhost:8080")!
    }

    /// MapLibre style; by default the engine's own map at {api}/v1/style.json. Empty: use Apple MapKit.
    static var mapStyleURL: URL? {
        guard let text = Bundle.main.object(forInfoDictionaryKey: "MixnavutsMapStyleURL") as? String, !text.isEmpty else { return nil }
        return URL(string: text)
    }
}
