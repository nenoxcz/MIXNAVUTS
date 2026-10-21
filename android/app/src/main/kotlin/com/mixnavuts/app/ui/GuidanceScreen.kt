package com.mixnavuts.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.mixnavuts.app.NavState
import com.mixnavuts.app.ui.map.RouteMap
import com.mixnavuts.core.SpeedSource

/**
 * Turn-by-turn screen. Every value comes from `HudState` (core), so this file is
 * pure layout — restyle it, or build the rally-style HUD on top of the same state.
 */
@Composable
fun GuidanceScreen(state: NavState, onStop: () -> Unit) {
    val update = state.navigation
    Column(Modifier.fillMaxSize()) {
        RouteMap(
            route = update?.route ?: state.selectedRoute,
            position = update?.let { it.progress.snappedLat to it.progress.snappedLon },
            bearing = update?.fix?.bearingDeg?.toFloat(),
            follow = true,
            modifier = Modifier.fillMaxWidth().weight(1f),
        )
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            val hud = update?.hud
            if (hud == null) {
                Text("위치를 찾는 중…")
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    hud.maneuverDistance?.let { Text(it, fontSize = 32.sp) }
                    Text(hud.maneuverText.orEmpty(), fontSize = 20.sp)
                }
                hud.thenText?.let { Text(it) }
                hud.lanes?.let { lanes -> Text("차로  " + lanes.joinToString(" ") { if (it) "▣" else "▢" }) }
                hud.alert?.let { Text(it) }
                hud.roadAhead?.let { Text("ROAD AHEAD  $it") }
                Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Text("${hud.speedKmh ?: "--"} km/h" + if (hud.speedSource == SpeedSource.VEHICLE) " (차량)" else "")
                    hud.limitKmh?.let { Text("제한 $it" + if (hud.overLimit) " · 속도 초과" else "") }
                }
                Text("도착 ${hud.eta} · ${hud.remainingTime} · ${hud.remainingDistance}")
                Text(hud.roadName)
                update?.rerouteError?.let { Text("재탐색 실패: $it") }
            }
            state.error?.let { Text(it) }
            Button(onClick = onStop, modifier = Modifier.fillMaxWidth()) { Text("안내 종료") }
        }
    }
}
