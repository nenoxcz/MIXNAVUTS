import MixnavutsKit
import SwiftUI

@main
struct MixnavutsApp: App {
    @StateObject private var controller = NavigationController.shared

    init() {
        NaverMapSetup.configure(clientId: AppConfig.naverMapClientId)
    }

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

    static var naverMapClientId: String {
        (Bundle.main.object(forInfoDictionaryKey: "NaverMapClientID") as? String) ?? ""
    }
}
