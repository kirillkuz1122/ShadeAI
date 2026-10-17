plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.shadeai.fixture"
    compileSdk = 35
    defaultConfig {
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "synthetic-task10"
    }
    flavorDimensions += "source"
    productFlavors {
        create("allowed") { dimension = "source"; applicationId = "ru.ozon.app.android" }
        create("privateSource") { dimension = "source"; applicationId = "org.telegram.messenger" }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
