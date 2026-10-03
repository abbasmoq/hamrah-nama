param(
    [ValidateSet("auto", "win32", "win64")]
    [string]$Architecture = "auto"
)

$ErrorActionPreference = "Stop"
if ($Architecture -eq "auto") {
    $Architecture = if ([Environment]::Is64BitProcess) { "win64" } else { "win32" }
}

$OutputDirectory = "dist\HamrahNama-portable-$Architecture"

python -m pip install --upgrade pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --onefile `
    --name "HamrahNama" `
    --distpath $OutputDirectory `
    --workpath "build\$Architecture" `
    --specpath "build\$Architecture" `
    main.py

$CachedTools = Join-Path $env:LOCALAPPDATA "HamrahNama\tools"
if (Test-Path -LiteralPath $CachedTools) {
    Copy-Item -LiteralPath $CachedTools -Destination (Join-Path $OutputDirectory "tools") -Recurse -Force
}

$Archive = "dist\HamrahNama-portable-$Architecture.zip"
Compress-Archive -Path "$OutputDirectory\*" -DestinationPath $Archive -Force

Write-Host "Portable build completed: $Archive"
Write-Host "برای خروجی win32 این اسکریپت را با Python 32-bit اجرا کنید."
