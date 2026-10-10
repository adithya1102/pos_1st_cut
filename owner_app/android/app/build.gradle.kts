import java.util.Properties

plugins {
    id("com.android.application")
    // Firebase: processes google-services.json into generated resources. Must
    // come after the Android plugin. Version is declared (apply false) in
    // settings.gradle.kts, mirroring customer_app.
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

// Upload key for Play Store releases. Same discipline as the Maps key above and
// byte-for-byte the shape customer_app already uses: read from a gitignored
// properties file, never hardcoded.
//
// The keystore itself lives OUTSIDE the repo (see storeFile in key.properties)
// because this repository is public — a gitignore slip should not be able to
// publish a signing key. When key.properties is absent (fresh clone, CI without
// secrets) the release build falls back to debug signing so the project still
// builds; such an artifact is NOT uploadable to Play, which is the point.
//
// WIRING ONLY. No keystore and no passwords are added by this change; owner_app
// release builds stay debug-signed until a key.properties is placed next to
// owner_app/android/.
val keystoreProperties: Properties? = rootProject.file("key.properties")
    .takeIf { it.exists() }
    ?.let { f -> Properties().apply { f.inputStream().use { load(it) } } }

android {
    namespace = "com.carevo.owner_app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        // REQUIRED by flutter_local_notifications 22.3.1, which the acceptance
        // alert depends on. Its AAR declares the requirement, so without this
        // the debug build fails at :app:checkDebugAarMetadata with
        // "Dependency ':flutter_local_notifications' requires core library
        // desugaring to be enabled for :app" — not at runtime, at build time.
        //
        // Needed even though this app never calls zonedSchedule(): the plugin
        // has relied on desugaring for backwards-compatible scheduling since
        // v10, and the requirement is on the dependency, not on which of its
        // APIs you use (see its README, "Gradle setup").
        //
        // Pairs with the coreLibraryDesugaring dependency below; both are
        // required and neither works alone.
        isCoreLibraryDesugaringEnabled = true
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

// The desugared JDK library itself. Version 2.1.4 is the one
// flutter_local_notifications 22.3.1 names in its own README and ships in its
// example app, so it is matched exactly rather than floated — a desugar version
// skew against the plugin's AAR is the kind of mismatch that surfaces as an
// obscure D8 failure rather than a clear one.
//
// `coreLibraryDesugaring` is its own configuration, not an implementation
// dependency: it supplies the backported java.time/java.util.stream classes D8
// rewrites calls onto. It does nothing unless
// isCoreLibraryDesugaringEnabled is set in compileOptions above.
dependencies {
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs:2.1.4")
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
