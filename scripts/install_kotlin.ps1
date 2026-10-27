param([switch]$Launch)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskPackage=Join-Path $taskRoot 'dist\Riffuna-0.2.1'
$taskSource=Join-Path $taskPackage 'Riffuna.runtime'
$taskRuntime=Join-Path $taskRoot 'Riffuna.runtime'
$taskTemporary=Join-Path $taskRoot 'Riffuna.runtime.next'
$taskBackup=Join-Path $taskRoot '.test-data\before-native-kotlin'
$taskExecutable=Join-Path $taskRoot 'Riffuna.exe'
if(-not(Test-Path -LiteralPath (Join-Path $taskSource 'Riffuna.exe')) -or -not(Test-Path -LiteralPath (Join-Path $taskPackage 'Riffuna.exe'))){throw 'Build the complete package first.'}
$taskManifestPath=Join-Path $taskPackage 'BUILD-MANIFEST.json'
if(-not(Test-Path -LiteralPath $taskManifestPath)){throw 'Package manifest is missing.'}
$taskManifest=Get-Content -LiteralPath $taskManifestPath -Raw|ConvertFrom-Json
if($taskManifest.diagnostics -ne 'passed' -or $taskManifest.launcher_sha256 -ne (Get-FileHash -LiteralPath (Join-Path $taskPackage 'Riffuna.exe') -Algorithm SHA256).Hash.ToLowerInvariant()){throw 'Package verification failed.'}
$taskSourceScript=Join-Path $taskSource 'app\resources\source-runtime\index.mjs'
if(-not $taskManifest.source_sha256 -or $taskManifest.source_sha256 -ne (Get-FileHash -LiteralPath $taskSourceScript -Algorithm SHA256).Hash.ToLowerInvariant()){throw 'Package source component does not match the build manifest.'}
if($taskManifest.application_jar -notmatch '^desktopApp-[A-Za-z0-9]+\.jar$'){throw 'Unexpected application JAR name.'}
$taskApplicationJar=Join-Path (Join-Path $taskSource 'app') $taskManifest.application_jar
if($taskManifest.application_sha256 -ne (Get-FileHash -LiteralPath $taskApplicationJar -Algorithm SHA256).Hash.ToLowerInvariant()){throw 'Application code does not match the build manifest.'}
$taskRunning=Get-Process Riffuna -ErrorAction SilentlyContinue|Where-Object{$_.Path -and ($_.Path -eq $taskExecutable -or $_.Path.StartsWith($taskRuntime,[StringComparison]::OrdinalIgnoreCase))}
if($taskRunning){throw 'Close Riffuna before installing the new version.'}
New-Item -ItemType Directory -Force -Path $taskBackup|Out-Null
if((Test-Path -LiteralPath $taskExecutable)-and -not(Test-Path -LiteralPath (Join-Path $taskBackup 'Riffuna.exe'))){Copy-Item -LiteralPath $taskExecutable -Destination (Join-Path $taskBackup 'Riffuna.exe');(Get-FileHash -LiteralPath $taskExecutable -Algorithm SHA256).Hash|Set-Content (Join-Path $taskBackup 'SHA256.txt')}
# Only generated application files are replaced; the user library is outside this tree.
if(Test-Path -LiteralPath $taskTemporary){
    $taskResolved=[IO.Path]::GetFullPath($taskTemporary)
    if($taskResolved -ne [IO.Path]::GetFullPath((Join-Path $taskRoot 'Riffuna.runtime.next'))){throw 'Unexpected staging path.'}
    Remove-Item -LiteralPath $taskResolved -Recurse -Force
}
Copy-Item -LiteralPath $taskSource -Destination $taskTemporary -Recurse
Copy-Item -LiteralPath $taskManifestPath -Destination (Join-Path $taskTemporary 'BUILD-MANIFEST.json') -Force
if(Test-Path -LiteralPath $taskRuntime){
    $taskPrevious=Join-Path $taskBackup ('runtime-'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
    $taskResolved=[IO.Path]::GetFullPath($taskRuntime);$taskResolvedBackup=[IO.Path]::GetFullPath($taskPrevious)
    if($taskResolved -ne [IO.Path]::GetFullPath((Join-Path $taskRoot 'Riffuna.runtime')) -or -not $taskResolvedBackup.StartsWith([IO.Path]::GetFullPath($taskBackup)+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Unexpected runtime paths.'}
    Move-Item -LiteralPath $taskResolved -Destination $taskResolvedBackup
}
Move-Item -LiteralPath $taskTemporary -Destination $taskRuntime
$taskNext=Join-Path $taskRoot 'Riffuna.exe.next'
Copy-Item -LiteralPath (Join-Path $taskPackage 'Riffuna.exe') -Destination $taskNext -Force
Move-Item -LiteralPath $taskNext -Destination $taskExecutable -Force
Write-Host "Installed: $taskExecutable"
if($Launch){
    $taskVariables=@('MUSICDESK_DATA_DIR','MUSICDESK_UI_REPORT','MUSICDESK_AUTOCLOSE_MS')
    $taskSaved=@{}
    try{foreach($taskName in $taskVariables){$taskSaved[$taskName]=[Environment]::GetEnvironmentVariable($taskName,'Process');[Environment]::SetEnvironmentVariable($taskName,$null,'Process')};Start-Process -FilePath $taskExecutable}
    finally{foreach($taskName in $taskVariables){[Environment]::SetEnvironmentVariable($taskName,$taskSaved[$taskName],'Process')}}
}
