package com.mixnavuts.app

import android.app.Application
import android.content.Context
import com.mixnavuts.app.ui.map.NaverMapSetup
import com.mixnavuts.core.MixnavutsApi

class MixnavutsApplication : Application() {
    lateinit var controller: NavigationController
        private set

    override fun onCreate() {
        super.onCreate()
        controller = NavigationController(this, MixnavutsApi(BuildConfig.MIXNAVUTS_API))
        NaverMapSetup.init(this, BuildConfig.NAVER_MAP_CLIENT_ID)
    }
}

/** The one controller shared by the phone UI, Android Auto and the cluster. */
val Context.navigation: NavigationController
    get() = (applicationContext as MixnavutsApplication).controller
