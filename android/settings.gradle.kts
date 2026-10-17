pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "ShadeAI"
include(":app")

if (providers.gradleProperty("notificationFixture").orNull == "true") {
    include(":notification-publisher")
    project(":notification-publisher").projectDir = file("checks/publisher")
}
