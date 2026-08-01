import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Maps API key is injected from a gitignored properties file — never hardcoded
// and never committed. Prefer android/maps.properties (Flutter rewrites
// local.properties on every build and would drop the key); local.properties is
// still read as a fallback. Missing key resolves to "" so a fresh clone still
// builds (Maps just won't authenticate until the key is supplied).
val mapsApiKey: String = Properties().apply {
    listOf("local.properties", "maps.properties").forEach { name ->
        val f = rootProject.file(name)
        if (f.exists()) f.inputStream().use { load(it) }
    }
}.getProperty("MAPS_API_KEY", "")

android {
    namespace = "com.carevo.owner_app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.carevo.owner_app"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        // Consumed by the com.google.android.geo.API_KEY meta-data in the manifest.
        manifestPlaceholders["MAPS_API_KEY"] = mapsApiKey
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
