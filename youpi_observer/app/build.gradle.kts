plugins {
    id("com.android.application")
}

android {
    namespace = "app.gustoskip.observer"
    compileSdk = 36

    defaultConfig {
        // Deliberately NOT com.carevo.* : this is a separate sideloaded app, so
        // the Firebase project and the two Play listings are untouched by it.
        // Also not com.youpi.observer, so it cannot collide with the gateway's
        // own prebuilt observer if that is ever installed alongside.
        applicationId = "app.gustoskip.observer"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Debug-signed on purpose: this is a sideloaded trial build and the
            // release keystores belong to the two store apps. Nothing here may
            // touch them.
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
}
