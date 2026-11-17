param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version = '0.3.0'
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskFramework = Join-Path $env:SystemRoot 'Microsoft.NET\Framework64\v4.0.30319'
$taskWinMetadata = Join-Path $env:SystemRoot 'System32\WinMetadata'
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$taskOutput = Join-Path (Resolve-Path -LiteralPath $OutputDirectory) 'RiffunaWindows.exe'
$taskReferences = @(
    (Join-Path $taskFramework 'System.Runtime.dll'),
    (Join-Path $taskFramework 'System.Runtime.WindowsRuntime.dll'),
    (Join-Path $taskFramework 'System.Runtime.InteropServices.WindowsRuntime.dll'),
    (Join-Path $taskFramework 'System.Windows.Forms.dll'),
    (Join-Path $taskWinMetadata 'Windows.Foundation.winmd'),
    (Join-Path $taskWinMetadata 'Windows.Media.winmd'),
    (Join-Path $taskWinMetadata 'Windows.Storage.winmd')
) | ForEach-Object { '/reference:' + $_ }
$taskArguments = @(
    '/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/codepage:65001',
    ("/win32icon:" + (Join-Path $taskRoot 'assets\riffuna.ico')),
    ("/out:" + $taskOutput)
) + $taskReferences + (Join-Path $taskRoot 'desktopApp\windows\RiffunaWindows.cs')
& (Join-Path $taskFramework 'csc.exe') @taskArguments
if($LASTEXITCODE -ne 0){throw 'Windows system media and installer helper build failed.'}

$Version | Set-Content -Encoding ascii -LiteralPath (Join-Path $OutputDirectory 'version.txt')
