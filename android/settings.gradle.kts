pluginManagement {
    repositories {
        mavenCentral()
        google()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositories {
        mavenCentral()
        google {
            content {
                includeGroupByRegex("androidx.*")
                includeGroupByRegex("com.android.*")
                includeGroupByRegex("com.google.android.*")
                includeGroupByRegex("com.google.testing.platform.*")
            }
        }
    }
}

rootProject.name = "RiffunaAndroid"

include(":app", ":core")
