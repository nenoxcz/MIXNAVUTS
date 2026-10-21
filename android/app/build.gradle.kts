import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

// 설정값: gradle 속성(-P) 또는 android/local.properties
//   mixnavuts.api=http://192.168.0.10:8080   엔진 API 주소 (기본: 에뮬레이터에서 본 PC)
//   mixnavuts.mapStyle=https://…/style.json   지도 스타일 (기본: 엔진의 자체 지도 {api}/v1/style.json, 빈 값이면 경로선만 그림)
val localProperties = Properties().apply {
    rootProject.file("local.properties").takeIf { it.exists() }?.inputStream()?.use { load(it) }
}

fun setting(name: String, default: String = ""): String =
    (project.findProperty(name) as String?) ?: localProperties.getProperty(name) ?: default

android {
    namespace = "com.mixnavuts.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.mixnavuts.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        val api = setting("mixnavuts.api", "http://10.0.2.2:8080")
        buildConfigField("String", "MIXNAVUTS_API", "\"$api\"")
        buildConfigField("String", "MAP_STYLE_URL", "\"${setting("mixnavuts.mapStyle", "$api/v1/style.json")}\"")
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
}

kotlin {
    compilerOptions { jvmTarget.set(JvmTarget.JVM_17) }
}

dependencies {
    implementation(project(":core"))
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.foundation)
    implementation(libs.compose.material3)
    implementation(libs.compose.ui.tooling.preview)
    debugImplementation(libs.compose.ui.tooling)
    implementation(libs.car.app)
    implementation(libs.car.app.projected)
    implementation(libs.maplibre)
}
