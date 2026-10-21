import MixnavutsKit
import SwiftUI

struct RootView: View {
    @EnvironmentObject private var controller: NavigationController

    var body: some View {
        if controller.navigating {
            GuidanceView()
        } else {
            NavigationStack { PlanView() }
        }
    }
}

/// Unstyled on purpose: layout and look are decided in the design pass.
struct PlanView: View {
    @EnvironmentObject private var controller: NavigationController
    @State private var query = ""

    var body: some View {
        Form {
            if controller.synthetic {
                Text("합성 도시 데이터로 동작 중")
            }

            Section("출발지") {
                Button {
                    controller.useCurrentLocationAsOrigin()
                } label: {
                    row("현재 위치", selected: controller.originIsCurrentLocation)
                }
                ForEach(controller.places) { place in
                    Button {
                        controller.setOrigin(place)
                    } label: {
                        row(place.name, selected: !controller.originIsCurrentLocation && controller.origin == place)
                    }
                }
            }

            Section("목적지") {
                HStack {
                    TextField("장소 검색", text: $query)
                    Button("검색") { Task { await controller.search(query) } }
                        .disabled(query.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                ForEach(controller.searchResults.isEmpty ? controller.places : controller.searchResults) { place in
                    Button {
                        controller.setDestination(place)
                    } label: {
                        VStack(alignment: .leading) {
                            row(place.name, selected: controller.destination == place)
                            if !place.address.isEmpty { Text(place.address).font(.caption) }
                        }
                    }
                }
            }

            Section("주행 목적") {
                Picker("모드", selection: $controller.mode) {
                    ForEach(NavigationController.modes) { mode in Text(mode.label).tag(mode.id) }
                }
                .pickerStyle(.segmented)
                Toggle("시뮬레이션 주행", isOn: $controller.simulate)
            }

            Section {
                Button(controller.loading ? "탐색 중…" : "경로 탐색") { Task { await controller.planRoutes() } }
                    .disabled(controller.loading || controller.destination == nil)
                if let message = controller.errorMessage { Text(message) }
            }

            if let plan = controller.plan {
                Section("후보 \(plan.candidates)개 검토 · \(plan.routes.count)개 제시 · 실시간 \(plan.live.source)") {
                    ForEach(Array(plan.routes.enumerated()), id: \.element.id) { index, route in
                        Button {
                            controller.selectedIndex = index
                        } label: {
                            VStack(alignment: .leading) {
                                row(route.labels.joined(separator: " · "), selected: index == controller.selectedIndex)
                                Text("도착 \(Format.clock(route.arrival)) · \(Format.duration(route.durationS)) · \(Format.distance(route.distanceM)) · \(Format.won(route.tollKrw))")
                                Text(route.summary).font(.caption)
                            }
                        }
                    }
                    RouteMapView(route: controller.selectedRoute, position: nil, bearing: nil, follow: false)
                        .frame(height: 240)
                    Button("안내 시작") { controller.start() }
                }
            }
        }
        .navigationTitle("MIXNAVUTS")
    }

    private func row(_ title: String, selected: Bool) -> some View {
        HStack {
            Text(title)
            Spacer()
            if selected { Image(systemName: "checkmark") }
        }
    }
}
