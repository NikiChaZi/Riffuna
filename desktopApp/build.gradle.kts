import org.jetbrains.compose.desktop.application.dsl.TargetFormat

plugins {
    kotlin("jvm")
    kotlin("plugin.serialization")
    id("org.jetbrains.compose")
    id("org.jetbrains.kotlin.plugin.compose")
}

kotlin { jvmToolchain(21) }

dependencies {
    implementation(project(":shared"))
    implementation(compose.desktop.currentOs)
    implementation(compose.material3)
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-swing:1.10.2")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")
    implementation("org.xerial:sqlite-jdbc:3.50.3.0")
    implementation("net.java.dev.jna:jna:5.17.0")
    implementation("net.java.dev.jna:jna-platform:5.17.0")
    implementation(compose.materialIconsExtended)
    implementation("sh.calvin.reorderable:reorderable:3.0.0")
    implementation("com.microsoft.onnxruntime:onnxruntime:1.23.2")
    implementation("org.bouncycastle:bcprov-jdk18on:1.82")
    implementation("org.slf4j:slf4j-nop:2.0.17")
    testImplementation(kotlin("test"))
}

compose.desktop {
    application {
        mainClass = "riffuna.desktop.MainKt"
        jvmArgs += listOf("--enable-native-access=ALL-UNNAMED")
        nativeDistributions {
            targetFormats(TargetFormat.Exe)
            appResourcesRootDir.set(
                rootProject.layout.projectDirectory.dir("build/desktop-resources")
            )
            packageName = "Riffuna"
            packageVersion = "0.2.1"
            modules("java.sql", "java.net.http", "jdk.crypto.ec", "jdk.httpserver")
            windows {
                iconFile.set(rootProject.file("assets/riffuna.ico"))
                menuGroup = "Riffuna"
                shortcut = true
            }
        }
    }
}

tasks.withType<JavaExec>().configureEach {
    systemProperty(
        "riffuna.home",
        rootProject.layout.buildDirectory.dir("desktop-resources/common").get().asFile.absolutePath,
    )
}

tasks.register<JavaExec>("renderUi") {
    dependsOn("testClasses")
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("riffuna.desktop.RenderUiKt")
    systemProperty("riffuna.project", rootProject.projectDir.absolutePath)
    systemProperty("java.awt.headless", "true")
    environment("MUSICDESK_DATA_DIR", rootProject.file(".test-data/full-ui-smoke").absolutePath)
}
