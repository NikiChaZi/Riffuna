param([switch]$DebugBuild, [switch]$LiveTest, [string]$DeviceSerial = '', [string]$TestFilter = '')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Push-Location $taskRoot
$taskSavedKeystore = $env:RIFFUNA_ANDROID_KEYSTORE
$taskSavedPassword = $env:RIFFUNA_ANDROID_KEY_PASSWORD
try {
    if (-not $env:JAVA_HOME -and (Test-Path '.tools/jdk-21.0.12.1+1')) {
        $env:JAVA_HOME = Join-Path $taskRoot '.tools/jdk-21.0.12.1+1'
    }
    if (-not $env:ANDROID_HOME -and (Test-Path '.tools/android-sdk')) {
        $env:ANDROID_HOME = Join-Path $taskRoot '.tools/android-sdk'
    }
    if (-not $env:GRADLE_USER_HOME -and (Test-Path '.tools/gradle-cache')) {
        $env:GRADLE_USER_HOME = Join-Path $taskRoot '.tools/gradle-cache'
    }
    $taskNode = (Get-Command node -ErrorAction Stop).Source
    & $taskNode scripts/build_android_source.mjs --restore-vendor
    if ($LASTEXITCODE -ne 0) { throw 'Install source dependencies first: npm ci --prefix source-runtime --ignore-scripts.' }
    & $taskNode scripts/build_android_source.mjs --check
    if ($LASTEXITCODE -ne 0) { throw 'Bundled Android source is out of date; run npm ci --prefix source-runtime --ignore-scripts and node scripts/build_android_source.mjs.' }
    if (-not $DebugBuild -and -not $env:RIFFUNA_ANDROID_KEYSTORE) {
        $taskSigning = Join-Path $env:USERPROFILE '.riffuna-developer/android-signing'
        $env:RIFFUNA_ANDROID_KEYSTORE = Join-Path $taskSigning 'riffuna.jks'
        $taskPasswordFile = Join-Path $taskSigning 'password.dpapi'
        if (-not (Test-Path -LiteralPath $env:RIFFUNA_ANDROID_KEYSTORE) -or -not (Test-Path -LiteralPath $taskPasswordFile)) { throw 'Release signing requires RIFFUNA_ANDROID_KEYSTORE and RIFFUNA_ANDROID_KEY_PASSWORD.' }
        $taskSecure = (Get-Content -LiteralPath $taskPasswordFile -Raw).Trim() | ConvertTo-SecureString
        $taskPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($taskSecure)
        try { $env:RIFFUNA_ANDROID_KEY_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($taskPointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($taskPointer) }
    }
    $taskVariant = if ($DebugBuild) { 'Debug' } else { 'Release' }
    $taskGradle = if ($env:OS -eq 'Windows_NT') { Join-Path $taskRoot 'gradlew.bat' } else { Join-Path $taskRoot 'gradlew' }
    $taskLocalGradle = Join-Path $taskRoot '.tools/gradle-8.14.3/bin/gradle.bat'
    if ($env:OS -eq 'Windows_NT' -and (Test-Path -LiteralPath $taskLocalGradle)) { $taskGradle = $taskLocalGradle }
    $taskArguments = @('-p', 'android', 'spotlessCheck', ':core:testAndroidHostTest', ':app:testDebugUnitTest', ':app:lintDebug', (':app:assemble' + $taskVariant), '--console=plain')
    if ($LiveTest) {
        if (-not $DebugBuild) { $taskArguments += '-PriffunaTestRelease=true' }
        $taskArguments += (':app:assemble' + $taskVariant + 'AndroidTest')
    }
    & $taskGradle @taskArguments
    if ($LASTEXITCODE -ne 0) { throw 'Android checks or build failed.' }
    $taskApk = Join-Path $taskRoot ('android/app/build/outputs/apk/' + $taskVariant.ToLowerInvariant() + '/app-' + $taskVariant.ToLowerInvariant() + '.apk')
    if (-not (Test-Path -LiteralPath $taskApk)) { throw 'Signed APK was not produced.' }
    if ($LiveTest) {
        $taskAdbName = if ($env:OS -eq 'Windows_NT') { 'adb.exe' } else { 'adb' }
        $taskAdb = Join-Path $env:ANDROID_HOME ('platform-tools/' + $taskAdbName)
        $taskDevice = if ($DeviceSerial) { @('-s', $DeviceSerial) } else { @() }
        & $taskAdb @taskDevice install --no-streaming -r $taskApk
        if ($LASTEXITCODE -ne 0) { throw 'APK installation failed.' }
        $taskTestApk = Join-Path $taskRoot ('android/app/build/outputs/apk/androidTest/' + $taskVariant.ToLowerInvariant() + '/app-' + $taskVariant.ToLowerInvariant() + '-androidTest.apk')
        & $taskAdb @taskDevice install --no-streaming -r $taskTestApk
        if ($LASTEXITCODE -ne 0) { throw 'Test APK installation failed.' }
        $taskTestPackage = if ($DebugBuild) { 'app.riffuna.player.debug.test' } else { 'app.riffuna.player.test' }
        $taskTestFilter = if ($TestFilter) { @('-e', 'class', $TestFilter) } else { @() }
        $taskTestOutput = & $taskAdb @taskDevice shell am instrument -w -e liveNetwork true @taskTestFilter ($taskTestPackage + '/androidx.test.runner.AndroidJUnitRunner')
        $taskTestOutput | Write-Output
        if ($LASTEXITCODE -ne 0 -or ($taskTestOutput -join "`n") -notmatch 'OK \(\d+ tests?\)' -or ($taskTestOutput -join "`n") -match 'FAILURES!!!|INSTRUMENTATION_FAILED') { throw 'Android device tests failed.' }
    }
    $taskDestination = Join-Path $taskRoot 'dist/android'
    New-Item -ItemType Directory -Force -Path $taskDestination | Out-Null
    $taskName = if ($DebugBuild) { 'Riffuna-android-debug.apk' } else { 'Riffuna-android.apk' }
    Copy-Item -LiteralPath $taskApk -Destination (Join-Path $taskDestination $taskName) -Force
    $taskHash = (Get-FileHash -LiteralPath (Join-Path $taskDestination $taskName) -Algorithm SHA256).Hash.ToLowerInvariant()
    "$taskHash  $taskName" | Set-Content -LiteralPath (Join-Path $taskDestination ($taskName + '.sha256')) -Encoding ascii
    Write-Output "Ready: dist/android/$taskName"
} finally {
    $env:RIFFUNA_ANDROID_KEYSTORE = $taskSavedKeystore
    $env:RIFFUNA_ANDROID_KEY_PASSWORD = $taskSavedPassword
    Pop-Location
}
