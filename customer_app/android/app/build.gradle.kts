import java.util.Properties

plugins {
    id("com.android.application")
    // Firebase: processes google-services.json into generated resources. Must come
    // after the Android plugin. Version is declared (apply false) in settings.gradle.kts.
    id("com.google.gms.google-services")
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

// Upload key for Play Store releases. Same discipline as the Maps key: read
// from a gitignored properties file, never hardcoded.
//
// The keystore itself lives OUTSIDE the repo (see storeFile in key.properties)
// because this repository is public — a gitignore slip should not be able to
// publish a signing key. When key.properties is absent (fresh clone, CI without
// secrets) the release build falls back to debug signing so the project still
// builds; such an artifact is NOT uploadable to Play, which is the point.
val keystoreProperties: Properties? = rootProject.file("key.properties")
    .takeIf { it.exists() }
    ?.let { f -> Properties().apply { f.inputStream().use { load(it) } } }

android {
    namespace = "com.carevo.customer_app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.carevo.customer_app"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        // Consumed by the com.google.android.geo.API_KEY meta-data in the manifest.
        manifestPlaceholders["MAPS_API_KEY"] = mapsApiKey
    }

    signingConfigs {
        // Only declared when key.properties exists, so a clone without the
        // secret still configures cleanly instead of failing at Gradle sync.
        if (keystoreProperties != null) {
            create("upload") {
                storeFile = file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            // Real upload key when it is available; debug otherwise so
            // `flutter run --release` still works on a machine without the
            // secret. A debug-signed bundle is rejected by Play, so this
            // fallback cannot silently ship an unsigned-for-release artifact.
            signingConfig = if (keystoreProperties != null) {
                signingConfigs.getByName("upload")
            } else {
                signingConfigs.getByName("debug")
            }
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

// NOTE: deliberately no `implementation(platform("com.google.firebase:firebase-bom:…"))`.
//
// The Firebase console's Gradle snippet assumes a native Android app. In a
// Flutter app the FlutterFire plugins already supply their own BoM — firebase_core
// 4.12.1 brings 34.15.0 — and declaring a different version here overrides theirs
// for the whole graph. Pinning 34.17.0 resolved firebase-common to 22.2.0, which
// no longer has FirebaseOptions.getRecaptchaSiteKey(); FlutterFirebaseCorePlugin
// calls it, so the app died on launch with NoSuchMethodError.
//
// Let firebase_core own the native versions: bump the pub package, not a BoM here.
