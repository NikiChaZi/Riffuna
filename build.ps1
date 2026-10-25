param([string]$DistPath = 'dist')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$originalBuildPath = $env:PATH
$pythonBase = & '.\.venv\Scripts\python.exe' -c "import sys; print(sys.base_prefix)"
if ($LASTEXITCODE -ne 0) { throw 'Python environment unavailable' }
# Resolve native dependencies only from this Python and Windows. Unrelated
# tools on PATH can expose incompatible same-named ICU/CRT libraries.
$env:PATH = @((Join-Path $PSScriptRoot '.venv\Scripts'), $pythonBase, (Join-Path $pythonBase 'Scripts'), (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join ';'
try {
    & '.\.venv\Scripts\python.exe' scripts\make_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed' }
    & '.\.venv\Scripts\python.exe' -m PyInstaller --clean --noconfirm --distpath $DistPath --onedir --windowed --name Riffuna --icon assets\riffuna.ico --recursive-copy-metadata yt-dlp --copy-metadata requests --copy-metadata urllib3 --copy-metadata certifi --copy-metadata charset-normalizer --copy-metadata idna --copy-metadata ytmusicapi --copy-metadata pyinstaller --copy-metadata PySide6 --copy-metadata PySide6_Essentials --copy-metadata PySide6_Addons --copy-metadata shiboken6 --collect-data ytmusicapi --collect-all yt_dlp_ejs launch.py
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    $releaseFolder = Join-Path (Join-Path $PSScriptRoot $DistPath) 'Riffuna'
    Copy-Item -LiteralPath 'LICENSE','README.md','CHANGELOG.md','THIRD_PARTY_NOTICES.md' -Destination $releaseFolder
    Copy-Item -LiteralPath 'LICENSES' -Destination $releaseFolder -Recurse
    $pythonLicense = Join-Path $pythonBase 'LICENSE.txt'
    if (Test-Path -LiteralPath $pythonLicense) { Copy-Item -LiteralPath $pythonLicense -Destination (Join-Path $releaseFolder 'PYTHON-LICENSE.txt') }
    Write-Output (Join-Path (Join-Path $PSScriptRoot $DistPath) 'Riffuna\Riffuna.exe')
}
finally {
    $env:PATH = $originalBuildPath
}
