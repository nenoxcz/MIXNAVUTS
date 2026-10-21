package com.mixnavuts.app.car

import android.text.SpannableString
import android.text.Spanned
import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.car.app.constraints.ConstraintManager
import androidx.car.app.model.Action
import androidx.car.app.model.DurationSpan
import androidx.car.app.model.ItemList
import androidx.car.app.model.ListTemplate
import androidx.car.app.model.MessageTemplate
import androidx.car.app.model.Row
import androidx.car.app.model.Template
import androidx.car.app.navigation.model.RoutePreviewNavigationTemplate
import androidx.car.app.versioning.CarAppApiLevels
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.mixnavuts.app.NavState
import com.mixnavuts.app.NavigationController
import com.mixnavuts.app.ui.MODE_LABELS
import com.mixnavuts.core.Format
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import java.time.ZoneId
import kotlin.math.roundToLong

/** Re-renders a car screen whenever the part of the state it shows changes. */
private fun <T> Screen.invalidateOn(controller: NavigationController, select: (NavState) -> T) {
    lifecycleScope.launch {
        repeatOnLifecycle(Lifecycle.State.STARTED) {
            controller.state.map(select).distinctUntilChanged().collect { invalidate() }
        }
    }
}

private fun listLimit(carContext: CarContext): Int =
    if (carContext.carAppApiLevel >= CarAppApiLevels.LEVEL_2) {
        carContext.getCarService(ConstraintManager::class.java).getContentLimit(ConstraintManager.CONTENT_LIMIT_TYPE_LIST)
    } else {
        6
    }

/** 목적지 선택. Origin is the phone's choice (or the current position on a real network). */
class DestinationScreen(carContext: CarContext, private val controller: NavigationController) : Screen(carContext) {
    init {
        invalidateOn(controller) { it.places to it.error }
    }

    override fun onGetTemplate(): Template {
        val state = controller.state.value
        val builder = ListTemplate.Builder().setTitle("목적지").setHeaderAction(Action.APP_ICON)
        if (state.places.isEmpty()) {
            state.error?.let { return MessageTemplate.Builder(it).setHeaderAction(Action.APP_ICON).build() }
            return builder.setLoading(true).build()
        }
        val list = ItemList.Builder()
        state.places.take(listLimit(carContext)).forEach { place ->
            list.addItem(
                Row.Builder()
                    .setTitle(place.name)
                    .addText(place.address.ifBlank { "모드: ${MODE_LABELS[state.mode] ?: state.mode}" })
                    .setBrowsable(true)
                    .setOnClickListener {
                        controller.setDestination(place)
                        controller.plan()
                        screenManager.push(RoutePreviewScreen(carContext, controller))
                    }
                    .build(),
            )
        }
        return builder.setSingleList(list.build()).build()
    }
}

/** 경로 미리보기: the 3–5 routes the engine picked, with the route drawn on the map surface. */
class RoutePreviewScreen(carContext: CarContext, private val controller: NavigationController) : Screen(carContext) {
    private val zone = ZoneId.systemDefault()

    init {
        invalidateOn(controller) { Triple(it.plan, it.loading, it.selectedIndex) to it.error }
    }

    override fun onGetTemplate(): Template {
        val state = controller.state.value
        val plan = state.plan
        val builder = RoutePreviewNavigationTemplate.Builder()
            .setTitle(state.destinationName.ifBlank { "경로" })
            .setHeaderAction(Action.BACK)
        if (plan == null || state.loading) {
            state.error?.takeIf { !state.loading }?.let { return MessageTemplate.Builder(it).setHeaderAction(Action.BACK).build() }
            return builder.setLoading(true).build()
        }
        if (plan.routes.isEmpty()) return MessageTemplate.Builder("경로가 없습니다").setHeaderAction(Action.BACK).build()

        val list = ItemList.Builder().setOnSelectedListener { controller.selectRoute(it) }
        plan.routes.forEach { route ->
            val title = SpannableString("  · " + route.labels.joinToString(" · "))
            title.setSpan(DurationSpan.create(route.durationS.roundToLong()), 0, 1, Spanned.SPAN_INCLUSIVE_INCLUSIVE)
            list.addItem(
                Row.Builder()
                    .setTitle(title)
                    .addText("도착 ${Format.clock(route.arrival, zone)} · ${Format.distance(route.distanceM)} · ${Format.won(route.tollKrw)}")
                    .build(),
            )
        }
        list.setSelectedIndex(state.selectedIndex.coerceIn(0, plan.routes.size - 1))
        return builder
            .setItemList(list.build())
            .setNavigateAction(
                Action.Builder()
                    .setTitle("안내 시작")
                    .setOnClickListener {
                        controller.start()
                        screenManager.push(GuidanceCarScreen(carContext, controller))
                    }
                    .build(),
            )
            .build()
    }
}

/** Turn-by-turn on the car display, or the cluster when `cluster` is true. */
class GuidanceCarScreen(
    carContext: CarContext,
    private val controller: NavigationController,
    private val cluster: Boolean = false,
) : Screen(carContext) {
    init {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                controller.state.collect { state ->
                    if (!state.navigating && !cluster) {
                        if (screenManager.stackSize > 1) {
                            screenManager.popToRoot()
                        } else {
                            screenManager.push(DestinationScreen(carContext, controller))
                        }
                    } else {
                        invalidate()
                    }
                }
            }
        }
    }

    override fun onGetTemplate(): Template = CarTemplates.navigationTemplate(controller.state.value) { controller.stop() }
}
