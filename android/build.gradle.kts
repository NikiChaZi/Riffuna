plugins {
    id("com.diffplug.spotless") version "7.2.1"
    id("com.android.application") version "8.11.1" apply false
    id("com.android.kotlin.multiplatform.library") version "8.11.1" apply false
    kotlin("android") version "2.2.20" apply false
    kotlin("multiplatform") version "2.2.20" apply false
    kotlin("plugin.serialization") version "2.2.20" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.2.20" apply false
}

spotless {
    kotlin {
        target("app/src/**/*.kt")
        ktfmt("0.54").kotlinlangStyle()
    }
    kotlinGradle {
        target("*.gradle.kts", "app/*.gradle.kts", "core/*.gradle.kts")
        ktfmt("0.54").kotlinlangStyle()
    }
}
