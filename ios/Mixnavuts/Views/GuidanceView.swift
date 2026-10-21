import MixnavutsKit
import SwiftUI

/// Turn-by-turn screen. Every value comes from `HudState` (MixnavutsKit), so this file is pure
/// layout — restyle it, or build the rally-style HUD on top of the same state.
struct GuidanceView: View {
    @EnvironmentObject private var controller: NavigationController

    var body: some View {
        let update = controller.update
        VStack(spacing: 0) {
            RouteMapView(
                route: update?.route ?? controller.selectedRoute,
                position: update.map { (lat: $0.progress.snappedLat, lon: $0.progress.snappedLon) },
                bearing: update?.fix.bearingDeg,
                follow: true
            )
            VStack(alignment: .leading, spacing: 4) {
                if let hud = update?.hud {
                    HStack(spacing: 12) {
                        if let turn = hud.turn { Image(systemName: turn.symbolName).font(.largeTitle) }
                        if let distance = hud.maneuverDistance { Text(distance).font(.largeTitle) }
                        Text(hud.maneuverText ?? "").font(.title3)
                    }
                    if let then = hud.thenText { Text(then) }
                    if let lanes = hud.lanes { Text("차로  " + lanes.map { $0 ? "▣" : "▢" }.joined(separator: " ")) }
                    if let alert = hud.alert { Text(alert) }
                    if let ahead = hud.roadAhead { Text("ROAD AHEAD  \(ahead)") }
                    HStack(spacing: 16) {
                        Text("\(hud.speedKmh.map { "\($0)" } ?? "--") km/h")
                        if let limit = hud.limitKmh { Text("제한 \(limit)\(hud.overLimit ? " · 속도 초과" : "")") }
                    }
                    Text("도착 \(hud.eta) · \(hud.remainingTime) · \(hud.remainingDistance)")
                    Text(hud.roadName)
                    if let error = update?.rerouteError { Text("재탐색 실패: \(error)") }
                } else {
                    Text("위치를 찾는 중…")
                }
                if let message = controller.errorMessage { Text(message) }
                Button("안내 종료") { controller.stop() }
                    .frame(maxWidth: .infinity)
                    .padding(.top, 8)
            }
            .padding()
        }
    }
}
