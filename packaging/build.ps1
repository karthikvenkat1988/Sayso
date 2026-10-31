<#
.SYNOPSIS
  Builds Sayso release artifacts into dist\. Needs Windows, Python 3.12 and no admin rights
  (the installer target also needs Inno Setup 6: ISCC.exe on PATH or in the default folder).

.EXAMPLE
  .\packaging\build.ps1 -Target portable,zipapp
  .\packaging\build.ps1 -Target all -Sign -CertThumbprint ABCDEF...
#>
[CmdletBinding()]
param(
    [ValidateSet("portable", "portable-offline", "onefile", "installer", "corporate", "zipapp", "all")]
    [string[]]$Target = @("portable"),
    [switch]$NoCloud,
    [switch]$Sign,
    [string]$CertThumbprint = "",
    [string]$Python = "py -3.12",
    [string]$FwModel = "base.en",
    [string]$GgmlModel = "base.en"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Native([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Command failed with exit code $LASTEXITCODE" }
}

$version = (Select-String -Path "src\sayso\__init__.py" -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$targets = if ($Target -contains "all") { @("portable", "portable-offline", "onefile", "installer", "corporate", "zipapp") } else { $Target }
Write-Host "Sayso $version -> $($targets -join ', ')"

# --- environment -------------------------------------------------------------------------------------------
if (-not (Test-Path ".venv-build")) {
    $parts = $Python -split " "
    Invoke-Native $parts[0] ($parts[1..($parts.Length - 1)] + @("-m", "venv", ".venv-build"))
}
$py = Join-Path $root ".venv-build\Scripts\python.exe"
Invoke-Native $py @("-m", "pip", "install", "--upgrade", "pip")
$extras = if ($NoCloud) { "local-stt,uia,dev" } else { "full,dev" }
Invoke-Native $py @("-m", "pip", "install", "-e", ".[$extras]")
Invoke-Native $py @("scripts\make_sounds.py")
Invoke-Native $py @("scripts\make_icons.py")

New-Item -ItemType Directory -Force -Path "dist" | Out-Null

function Invoke-Sign([string]$Path) {
    if (-not $Sign) { return }
    if (-not $CertThumbprint) { throw "-Sign needs -CertThumbprint" }
    Invoke-Native "signtool" @("sign", "/sha1", $CertThumbprint, "/fd", "sha256", "/tr", "http://timestamp.digicert.com", "/td", "sha256", $Path)
}

function Invoke-PyInstaller([bool]$OneFile) {
    $env:ONEFILE = if ($OneFile) { "1" } else { "0" }
    $env:NO_CLOUD = if ($NoCloud) { "1" } else { "0" }
    Invoke-Native $py @("-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", "dist\pyi", "--workpath", "build\pyi",
        "packaging\pyinstaller\sayso.spec")
}

function New-Zip([string]$SourceDir, [string]$ZipPath) {
    if (Test-Path $ZipPath) { Remove-Item $ZipPath }
    Compress-Archive -Path "$SourceDir\*" -DestinationPath $ZipPath -CompressionLevel Optimal
    Write-Host "  -> $ZipPath"
}

function Copy-Portable([string]$Dest) {
    if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
    Copy-Item -Recurse "dist\pyi\Sayso" $Dest
    New-Item -ItemType File -Force -Path (Join-Path $Dest "portable") | Out-Null
    Copy-Item "packaging\README-portable.txt" (Join-Path $Dest "README-portable.txt")
    Copy-Item "config\settings.example.json" (Join-Path $Dest "settings.example.json")
}

function Add-OfflineModels([string]$Dest) {
    $extras = Join-Path $root "build\extras"
    Invoke-Native $py @("packaging\fetch_models.py", "--out", $extras, "--fw", $FwModel, "--ggml", $GgmlModel)
    Copy-Item -Recurse -Force (Join-Path $extras "models") (Join-Path $Dest "models")
    Copy-Item -Recurse -Force (Join-Path $extras "bin") (Join-Path $Dest "bin")
}

$needDir = $targets | Where-Object { $_ -in @("portable", "portable-offline", "installer", "corporate") }
if ($needDir) { Invoke-PyInstaller $false; Invoke-Sign "dist\pyi\Sayso\Sayso.exe" }

foreach ($t in $targets) {
    Write-Host "== $t"
    switch ($t) {
        "portable" {
            Copy-Portable "build\portable"
            New-Zip "build\portable" "dist\Sayso-$version-portable-win-x64.zip"
        }
        "portable-offline" {
            Copy-Portable "build\portable-offline"
            Add-OfflineModels "build\portable-offline"
            New-Zip "build\portable-offline" "dist\Sayso-$version-portable-offline-win-x64.zip"
        }
        "corporate" {
            Copy-Portable "build\corporate"
            Add-OfflineModels "build\corporate"
            Copy-Item "packaging\corporate\policy.json" "build\corporate\policy.json"
            New-Zip "build\corporate" "dist\Sayso-$version-corporate-win-x64.zip"
        }
        "onefile" {
            Invoke-PyInstaller $true
            $out = "dist\Sayso-$version-win-x64.exe"
            Copy-Item "dist\pyi\Sayso.exe" $out -Force
            Invoke-Sign $out
            Write-Host "  -> $out"
        }
        "installer" {
            $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
            if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
            if (-not (Test-Path $iscc)) { throw "Inno Setup 6 not found. Install it, or build without the installer target." }
            Invoke-Native $iscc @("/DAppVersion=$version", "/DSourceDir=$root\dist\pyi\Sayso", "packaging\installer\sayso.iss")
            Invoke-Sign "dist\Sayso-$version-setup.exe"
        }
        "zipapp" {
            Invoke-Native $py @("packaging\make_zipapp.py")
        }
    }
}

# --- checksums ---------------------------------------------------------------------------------------------
$lines = Get-ChildItem "dist" -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" } |
    ForEach-Object { "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name }
Set-Content -Path "dist\SHA256SUMS.txt" -Value $lines -Encoding ascii
Write-Host "Done. See dist\"
