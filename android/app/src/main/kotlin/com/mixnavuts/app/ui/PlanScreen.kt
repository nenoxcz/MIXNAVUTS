package com.mixnavuts.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mixnavuts.app.NavState
import com.mixnavuts.app.NavigationController
import com.mixnavuts.app.ui.map.RouteMap
import com.mixnavuts.core.Format
import com.mixnavuts.core.Place
import java.time.ZoneId

val MODE_LABELS = linkedMapOf(
    "balanced" to "추천",
    "fastest" to "최단시간",
    "economy" to "경제",
    "highway" to "고속도로",
    "scenic" to "와인딩",
)

/** Unstyled on purpose: layout and look are decided in the design pass. */
@Composable
fun PlanScreen(state: NavState, controller: NavigationController, requestLocation: () -> Unit) {
    val zone = ZoneId.systemDefault()
    var query by remember { mutableStateOf("") }
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item {
            Text("MIXNAVUTS")
            if (state.synthetic) Text("합성 도시 데이터로 동작 중")
        }

        item { Text("출발지: " + if (state.originIsCurrentLocation) "현재 위치" else state.origin?.name ?: "선택 안 함") }
        item {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                item {
                    FilterChip(
                        selected = state.originIsCurrentLocation,
                        onClick = {
                            if (!controller.location.hasPermission()) requestLocation()
                            controller.useCurrentLocationAsOrigin()
                        },
                        label = { Text("현재 위치") },
                    )
                }
                items(state.places) { place ->
                    FilterChip(
                        selected = !state.originIsCurrentLocation && state.origin == place,
                        onClick = { controller.setOrigin(place) },
                        label = { Text(place.name) },
                    )
                }
            }
        }

        item { Text("목적지: " + (state.destination?.name ?: "선택 안 함")) }
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(value = query, onValueChange = { query = it }, label = { Text("장소 검색") }, modifier = Modifier.weight(1f))
                Spacer(Modifier.width(8.dp))
                Button(onClick = { controller.search(query) }, enabled = query.isNotBlank()) { Text("검색") }
            }
        }
        items(state.searchResults.ifEmpty { state.places }) { place -> PlaceRow(place) { controller.setDestination(place) } }

        item {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(MODE_LABELS.entries.toList()) { (mode, label) ->
                    FilterChip(selected = state.mode == mode, onClick = { controller.setMode(mode) }, label = { Text(label) })
                }
            }
        }
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("시뮬레이션 주행", modifier = Modifier.weight(1f))
                Switch(
                    checked = state.simulate,
                    onCheckedChange = {
                        if (!it && !controller.location.hasPermission()) requestLocation()
                        controller.setSimulate(it)
                    },
                )
            }
        }
        item {
            Button(
                onClick = { controller.plan() },
                enabled = !state.loading && state.destination != null && (state.origin != null || state.originIsCurrentLocation),
                modifier = Modifier.fillMaxWidth(),
            ) { Text(if (state.loading) "탐색 중…" else "경로 탐색") }
        }
        state.error?.let { message ->
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(message, modifier = Modifier.weight(1f))
                    TextButton(onClick = controller::clearError) { Text("닫기") }
                }
            }
        }

        state.plan?.let { plan ->
            item { Text("후보 ${plan.candidates}개 검토 · ${plan.routes.size}개 제시 · 실시간 ${plan.live.source}") }
            itemsIndexed(plan.routes) { index, route ->
                Row(
                    modifier = Modifier.fillMaxWidth().clickable { controller.selectRoute(index) },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    RadioButton(selected = index == state.selectedIndex, onClick = { controller.selectRoute(index) })
                    Column {
                        Text(route.labels.joinToString(" · "))
                        Text(
                            "도착 ${Format.clock(route.arrival, zone)} · ${Format.duration(route.durationS)} · " +
                                "${Format.distance(route.distanceM)} · ${Format.won(route.tollKrw)}",
                        )
                        Text(route.summary)
                    }
                }
                HorizontalDivider()
            }
            item { RouteMap(route = state.selectedRoute, position = null, follow = false, modifier = Modifier.fillMaxWidth().height(240.dp)) }
            item {
                Button(onClick = { controller.start() }, enabled = state.selectedRoute != null, modifier = Modifier.fillMaxWidth()) {
                    Text("안내 시작")
                }
            }
        }
    }
}

@Composable
private fun PlaceRow(place: Place, onClick: () -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 6.dp)) {
        Text(place.name)
        if (place.address.isNotBlank()) Text(place.address)
    }
}
