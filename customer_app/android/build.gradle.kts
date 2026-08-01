allprojects {
    repositories {
        google()
        mavenCentral()
    }
    // flutter_google_places_sdk_android 0.2.2 defaults to Places SDK 5.1.1, but
    // its Kotlin uses classic Place getters (address/latLng/name/...) that only
    // exist through the 3.x line. Pin to 3.5.0 so the plugin compiles.
    configurations.all {
        resolutionStrategy.eachDependency {
            if (requested.group == "com.google.android.libraries.places" &&
                requested.name == "places") {
                useVersion("3.5.0")
            }
        }
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
