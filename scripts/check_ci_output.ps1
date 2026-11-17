param(
    [Parameter(Mandatory)][ValidateSet('Windows', 'AndroidDebug', 'AndroidRelease')][string]$Platform
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $repo
try {
    $directory = Join-Path $repo 'build/privacy-ci'
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $log = Join-Path $directory ($Platform + '.log')
    $code = 0
    try {
        switch ($Platform) {
            Windows {
                $env:RIFFUNA_LIVE_TEST = '0'
                $env:RIFFUNA_CATALOGUE_TEST = '0'
                & .\gradlew.bat spotlessCheck :shared:jvmTest :desktopApp:test --no-daemon --console=plain *> $log
                $code = $LASTEXITCODE
            }
            AndroidDebug { & ./scripts/build_android.ps1 -DebugBuild *> $log }
            AndroidRelease { & ./scripts/build_android.ps1 *> $log }
        }
    } catch {
        # Do not emit exception details beyond the captured and checked log.
        $code = 1
    }
    & python scripts/check_release_payload.py $log
    if ($LASTEXITCODE -ne 0) { throw 'Build output withheld because the privacy check failed.' }
    Get-Content -LiteralPath $log
    if ($code -ne 0) { exit $code }
} finally {
    Pop-Location
}
