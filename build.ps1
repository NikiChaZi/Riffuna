param([string]$DistPath = 'dist', [string]$Python = (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'))
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$libmpvPath = Join-Path $PSScriptRoot 'vendor\libmpv\libmpv-2.dll'
if (-not (Test-Path -LiteralPath $libmpvPath -PathType Leaf)) {
    throw 'libmpv is missing. Run .venv\Scripts\python.exe scripts\fetch_mpv.py first.'
}
$originalBuildPath = $env:PATH
$Python = (Resolve-Path -LiteralPath $Python).Path
$pythonBase = & $Python -c "import sys; print(sys.base_prefix)"
if ($LASTEXITCODE -ne 0) { throw 'Python environment unavailable' }
# Resolve native dependencies only from this Python and Windows. Unrelated
# tools on PATH can expose incompatible same-named ICU/CRT libraries.
$env:PATH = @((Split-Path -Parent $Python), $pythonBase, (Join-Path $pythonBase 'Scripts'), (Join-Path $env:SystemRoot 'System32'), $env:SystemRoot) -join ';'
try {
    & $Python scripts\prepare_music_model.py
    if ($LASTEXITCODE -ne 0) { throw 'Music model staging failed' }
    & $Python scripts\make_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed' }
    & $Python scripts\write_version_info.py
    if ($LASTEXITCODE -ne 0) { throw 'Version metadata generation failed' }
    & $Python -m PyInstaller --clean --noconfirm --distpath $DistPath --onefile --windowed --name Riffuna --version-file build\version-info.txt --icon assets\riffuna.ico --add-data "assets;assets" --add-data "build\music-model;music-model" --add-data "LICENSES;LICENSES" --add-data "$pythonBase\LICENSE.txt;LICENSES" --add-data "LICENSE;." --add-data "LICENSING.md;." --add-data "THIRD_PARTY_NOTICES.md;." --add-data "README.md;." --add-data "CHANGELOG.md;." --add-binary "vendor\libmpv\libmpv-2.dll;vendor\libmpv" --recursive-copy-metadata yt-dlp --copy-metadata requests --copy-metadata urllib3 --copy-metadata certifi --copy-metadata charset-normalizer --copy-metadata idna --copy-metadata ytmusicapi --copy-metadata pyinstaller --copy-metadata PySide6 --copy-metadata PySide6_Essentials --copy-metadata PySide6_Addons --copy-metadata shiboken6 --collect-data ytmusicapi --collect-all yt_dlp_ejs launch.py
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    Write-Output (Join-Path (Join-Path $PSScriptRoot $DistPath) 'Riffuna.exe')
}
finally {
    $env:PATH = $originalBuildPath
}
