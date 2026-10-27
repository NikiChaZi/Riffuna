param([switch]$LiveTest)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
Push-Location $taskRoot
try {
    $taskLocal=Join-Path $taskRoot '.test-data\kotlin-toolchain.json'
    if(Test-Path -LiteralPath $taskLocal){
        $taskToolchain=Get-Content -LiteralPath $taskLocal -Raw|ConvertFrom-Json
        $env:JAVA_HOME=$taskToolchain.jdk
        $env:GRADLE_USER_HOME=Join-Path $taskRoot '.tools\gradle-cache'
        $taskGradle=Join-Path $taskToolchain.gradle 'bin\gradle.bat'
    }else{
        if(-not $env:JAVA_HOME){throw 'Set JAVA_HOME to a JDK 21 installation.'}
        $taskGradle=Join-Path $taskRoot 'gradlew.bat'
    }
    $taskNode=(Get-Command node.exe -ErrorAction Stop).Source
    $taskNodeVersion=(& $taskNode --version).Trim()
    if([version]$taskNodeVersion.TrimStart('v') -lt [version]'24.5.0'){throw 'Node.js 24.5 or newer is required on the build machine.'}
    $taskLockHash=(Get-FileHash -LiteralPath source-runtime/package-lock.json -Algorithm SHA256).Hash
    $taskLockStamp=Join-Path $taskRoot 'source-runtime\node_modules\.riffuna-lock-sha256'
    $taskInstalledHash=if(Test-Path -LiteralPath $taskLockStamp){(Get-Content -LiteralPath $taskLockStamp -Raw).Trim()}else{''}
    if($taskInstalledHash -ne $taskLockHash -or -not(Test-Path source-runtime/node_modules/undici/package.json)){
        & (Join-Path (Split-Path $taskNode -Parent) 'npm.cmd') ci --prefix source-runtime --ignore-scripts --no-audit --no-fund
        if($LASTEXITCODE -ne 0){throw 'YouTube component install failed.'}
        $taskLockHash|Set-Content -LiteralPath $taskLockStamp -Encoding ascii
    }
    $taskResources=Join-Path $taskRoot 'build\desktop-resources\common'
    if(Test-Path -LiteralPath $taskResources){
        $taskResolved=[IO.Path]::GetFullPath($taskResources)
        $taskAllowed=[IO.Path]::GetFullPath((Join-Path $taskRoot 'build'))+[IO.Path]::DirectorySeparatorChar
        if(-not $taskResolved.StartsWith($taskAllowed,[StringComparison]::OrdinalIgnoreCase)){throw 'Unexpected build resources path.'}
        Remove-Item -LiteralPath $taskResolved -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $taskResources 'assets'),(Join-Path $taskResources 'vendor\node'),(Join-Path $taskResources 'vendor\libmpv'),(Join-Path $taskResources 'source-runtime'),(Join-Path $taskResources 'LICENSES')|Out-Null
    Copy-Item -Path assets/riffuna.* -Destination (Join-Path $taskResources 'assets') -Force
    Copy-Item -LiteralPath $taskNode -Destination (Join-Path $taskResources 'vendor\node\node.exe') -Force
    Copy-Item -Path source-runtime/index.mjs,source-runtime/package.json,source-runtime/package-lock.json,source-runtime/node_modules -Destination (Join-Path $taskResources 'source-runtime') -Recurse -Force
    Copy-Item -LiteralPath vendor/libmpv/libmpv-2.dll,vendor/libmpv/LICENSE.LGPL,vendor/libmpv/BUILD-MANIFEST.json -Destination (Join-Path $taskResources 'vendor\libmpv') -Force
    Copy-Item -Path LICENSES/* -Destination (Join-Path $taskResources 'LICENSES') -Force
    Copy-Item -LiteralPath LICENSE,LICENSING.md,THIRD_PARTY_NOTICES.md -Destination $taskResources -Force
    @{version=$taskNodeVersion;sha256=(Get-FileHash -LiteralPath $taskNode -Algorithm SHA256).Hash.ToLowerInvariant();source="https://nodejs.org/dist/$taskNodeVersion/win-x64/node.exe"}|ConvertTo-Json|Set-Content (Join-Path $taskResources 'vendor\node\BUILD-MANIFEST.json') -Encoding utf8
    if(Test-Path -LiteralPath build/kotlin-music-model/manifest.json){
        New-Item -ItemType Directory -Force -Path (Join-Path $taskResources 'music-model')|Out-Null
        Copy-Item -Path build/kotlin-music-model/* -Destination (Join-Path $taskResources 'music-model') -Force
    }else{throw 'Export the trained music models to build/kotlin-music-model first.'}
    $taskImage=Join-Path $taskRoot 'desktopApp\build\compose\binaries\main\app\Riffuna'
    $taskRunning=Get-Process Riffuna -ErrorAction SilentlyContinue|Where-Object{$_.Path -and $_.Path.StartsWith($taskImage,[StringComparison]::OrdinalIgnoreCase)}
    if($taskRunning){throw 'Close the running build of Riffuna before packaging.'}
    if(Test-Path -LiteralPath $taskImage){
        $taskResolved=[IO.Path]::GetFullPath($taskImage)
        $taskAllowed=[IO.Path]::GetFullPath((Join-Path $taskRoot 'desktopApp\build'))+[IO.Path]::DirectorySeparatorChar
        if(-not $taskResolved.StartsWith($taskAllowed,[StringComparison]::OrdinalIgnoreCase)){throw 'Unexpected application image path.'}
        Remove-Item -LiteralPath $taskResolved -Recurse -Force
    }
    $taskPreviousLive=$env:RIFFUNA_LIVE_TEST
    try {
        $env:RIFFUNA_LIVE_TEST=if($LiveTest){'1'}else{'0'}
        & $taskGradle :shared:jvmTest :desktopApp:test :desktopApp:createDistributable --no-daemon --console=plain
        if($LASTEXITCODE -ne 0){throw 'Kotlin build failed.'}
    }finally{$env:RIFFUNA_LIVE_TEST=$taskPreviousLive}
    $taskOutput=Join-Path $taskRoot 'dist\Riffuna-0.2.1'
    $taskRuntime=Join-Path $taskOutput 'Riffuna.runtime'
    $taskRunning=Get-Process Riffuna -ErrorAction SilentlyContinue|Where-Object{$_.Path -and $_.Path.StartsWith($taskOutput,[StringComparison]::OrdinalIgnoreCase)}
    if($taskRunning){throw 'Close the packaged Riffuna before updating its files.'}
    if(Test-Path -LiteralPath $taskOutput){
        $taskResolved=[IO.Path]::GetFullPath($taskOutput)
        $taskAllowed=[IO.Path]::GetFullPath((Join-Path $taskRoot 'dist'))+[IO.Path]::DirectorySeparatorChar
        if(-not $taskResolved.StartsWith($taskAllowed,[StringComparison]::OrdinalIgnoreCase)){throw 'Unexpected package path.'}
        Remove-Item -LiteralPath $taskResolved -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $taskRuntime|Out-Null
    Copy-Item -Path (Join-Path $taskImage '*') -Destination $taskRuntime -Recurse -Force
    $taskCompiler=Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    & $taskCompiler /nologo /target:winexe /platform:x64 /optimize+ ("/win32icon:"+(Join-Path $taskRoot 'assets\riffuna.ico')) ("/out:"+(Join-Path $taskOutput 'Riffuna.exe')) /reference:System.Windows.Forms.dll (Join-Path $taskRoot "desktopApp\windows\Launcher.cs")
    if($LASTEXITCODE -ne 0){throw 'Launcher build failed.'}
    Copy-Item -LiteralPath LICENSE,LICENSING.md,THIRD_PARTY_NOTICES.md -Destination $taskOutput -Force
    $taskForbidden=Get-ChildItem -LiteralPath $taskRuntime -Recurse -File|Where-Object{$_.Name -match '^(python.*\.dll|RiffunaSource\.exe|Qt[56].*\.dll)$' -or $_.Extension -in '.pyc','.pyo'}
    if($taskForbidden){throw 'Legacy Python/Qt files entered the package.'}
    $taskDiagnosticReport=Join-Path $taskRoot '.test-data\native-package-report.json'
    if(Test-Path -LiteralPath $taskDiagnosticReport){Remove-Item -LiteralPath $taskDiagnosticReport -Force}
    $taskDiagnostic=Start-Process -FilePath (Join-Path $taskRuntime 'Riffuna.exe') -ArgumentList @('--diagnose','--report',('"'+$taskDiagnosticReport+'"')) -WindowStyle Hidden -PassThru
    if(-not $taskDiagnostic.WaitForExit(30000)){$taskDiagnostic.Kill();throw 'Packaged runtime diagnostic timed out.'}
    if($taskDiagnostic.ExitCode -ne 0 -or -not(Test-Path -LiteralPath $taskDiagnosticReport)){throw 'Packaged runtime diagnostic failed.'}
    $taskReport=Get-Content -LiteralPath $taskDiagnosticReport -Raw|ConvertFrom-Json
    if($taskReport.status -ne 'ok' -or $taskReport.python_runtime -ne $false -or $taskReport.qt_runtime -ne $false){throw 'Unexpected packaged runtime report.'}
    $taskApplicationJar=Get-ChildItem -LiteralPath (Join-Path $taskRuntime 'app') -Filter 'desktopApp-*.jar' -File|Select-Object -First 1
    if(-not $taskApplicationJar){throw 'Application JAR is missing.'}
    @{version='0.2.1';application_jar=$taskApplicationJar.Name;application_sha256=(Get-FileHash -LiteralPath $taskApplicationJar.FullName -Algorithm SHA256).Hash.ToLowerInvariant();launcher_sha256=(Get-FileHash -LiteralPath (Join-Path $taskOutput 'Riffuna.exe') -Algorithm SHA256).Hash.ToLowerInvariant();source_lock_sha256=$taskLockHash.ToLowerInvariant();source_sha256=(Get-FileHash -LiteralPath source-runtime/index.mjs -Algorithm SHA256).Hash.ToLowerInvariant();diagnostics='passed';live_source_test=$(if($LiveTest){'passed'}else{'not_run'});built_at_utc=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $taskOutput 'BUILD-MANIFEST.json') -Encoding utf8
    Write-Host "Ready: $taskOutput\Riffuna.exe"
}finally{Pop-Location}
