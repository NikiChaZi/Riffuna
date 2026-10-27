plugins {
    id("com.diffplug.spotless") version "7.2.1"
    kotlin("multiplatform") version "2.2.20" apply false
    kotlin("jvm") version "2.2.20" apply false
    kotlin("plugin.serialization") version "2.2.20" apply false
    id("org.jetbrains.compose") version "1.9.1" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.2.20" apply false
}

spotless {
    kotlin {
        target("shared/src/**/*.kt", "desktopApp/src/**/*.kt")
        ktfmt("0.54").kotlinlangStyle()
    }
    kotlinGradle {
        target("*.gradle.kts", "shared/*.gradle.kts", "desktopApp/*.gradle.kts")
        ktfmt("0.54").kotlinlangStyle()
    }
}

subprojects {
    tasks
        .matching { it.name == "check" }
        .configureEach { dependsOn(rootProject.tasks.named("spotlessCheck")) }
}
