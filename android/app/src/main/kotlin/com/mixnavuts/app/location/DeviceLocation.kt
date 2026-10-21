package com.mixnavuts.app.location

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Looper
import androidx.core.content.ContextCompat
import com.mixnavuts.core.Fix
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

/** GNSS fixes from the platform LocationManager (no Google Play services needed). */
class DeviceLocation(private val context: Context) {
    private val manager: LocationManager = context.getSystemService(LocationManager::class.java)

    fun hasPermission(): Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("MissingPermission")
    fun lastKnown(): Fix? {
        if (!hasPermission()) return null
        return listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
            .mapNotNull { provider -> runCatching { manager.getLastKnownLocation(provider) }.getOrNull() }
            .maxByOrNull { it.time }
            ?.toFix()
    }

    @SuppressLint("MissingPermission")
    fun fixes(intervalMs: Long = 1_000L): Flow<Fix> = callbackFlow {
        if (!hasPermission()) throw SecurityException("위치 권한이 필요합니다")
        // All four callbacks are implemented: before API 30 they are abstract.
        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                trySend(location.toFix())
            }

            @Deprecated("Deprecated in Java")
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) = Unit

            override fun onProviderEnabled(provider: String) = Unit

            override fun onProviderDisabled(provider: String) = Unit
        }
        manager.requestLocationUpdates(LocationManager.GPS_PROVIDER, intervalMs, 0f, listener, Looper.getMainLooper())
        awaitClose { manager.removeUpdates(listener) }
    }
}

fun Location.toFix() = Fix(
    time = time / 1000.0,
    lat = latitude,
    lon = longitude,
    speedMps = if (hasSpeed()) speed.toDouble() else null,
    accuracyM = if (hasAccuracy()) accuracy.toDouble() else null,
    bearingDeg = if (hasBearing()) bearing.toDouble() else null,
)
