param(
    [string]$Python = (Join-Path (Split-Path -Parent $PSScriptRoot) '.venv\Scripts\python.exe'),
    [switch]$Packaged
)
$ErrorActionPreference = 'Stop'
$riffunaRoot = Split-Path -Parent $PSScriptRoot
$riffunaMode = if ($Packaged) { 'packaged' } else { 'source' }
$riffunaPrevious = @{}
foreach ($key in @('QT_QPA_PLATFORM', 'MUSICDESK_DATA_DIR', 'MUSICDESK_UI_REPORT', 'MUSICDESK_AUTOCLOSE_MS')) {
    $riffunaPrevious[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
try {
    $env:QT_QPA_PLATFORM = 'windows'
    $env:MUSICDESK_DATA_DIR = Join-Path $riffunaRoot ('.test-data\native-' + $riffunaMode)
    $env:MUSICDESK_UI_REPORT = Join-Path $riffunaRoot ('.test-data\native-' + $riffunaMode + '-report.json')
    $env:MUSICDESK_AUTOCLOSE_MS = '1800'
    $riffunaStartedUtc = (Get-Date).ToUniversalTime()
    if ($Packaged) {
        $riffunaExecutable = Join-Path $riffunaRoot 'Riffuna.exe'
        $riffunaProcess = Start-Process -FilePath $riffunaExecutable -WorkingDirectory $riffunaRoot -WindowStyle Hidden -PassThru
    } else {
        $riffunaProcess = Start-Process -FilePath $Python -ArgumentList 'launch.py' -WorkingDirectory $riffunaRoot -WindowStyle Hidden -PassThru
    }
    if (-not $riffunaProcess.WaitForExit(45000)) { throw 'Isolated UI did not exit in time' }
    if ($riffunaProcess.ExitCode -ne 0) { throw ('UI exited with ' + $riffunaProcess.ExitCode) }
    if ((Get-Item -LiteralPath $env:MUSICDESK_UI_REPORT).LastWriteTimeUtc -lt $riffunaStartedUtc) { throw 'Startup report was not refreshed' }
    $riffunaReport = Get-Content -LiteralPath $env:MUSICDESK_UI_REPORT -Raw | ConvertFrom-Json
    if (-not ($riffunaReport.application_icon -and $riffunaReport.window_icon -and $riffunaReport.native_small_icon -and $riffunaReport.native_big_icon)) {
        throw 'Native application/window icons were not installed'
    }
    if ($riffunaReport.windows_app_id -ne 'Riffuna.Desktop') { throw 'Unexpected Windows application identity' }
    if ($riffunaReport.frozen -ne [bool]$Packaged) { throw 'Unexpected startup mode' }
    foreach ($size in @(16, 24, 32, 48, 256)) {
        if ($size -notin $riffunaReport.icon_sizes) { throw ('Missing runtime icon size: ' + $size) }
    }
    $riffunaReport | ConvertTo-Json -Depth 3
} finally {
    foreach ($key in $riffunaPrevious.Keys) {
        [Environment]::SetEnvironmentVariable($key, $riffunaPrevious[$key], 'Process')
    }
}
