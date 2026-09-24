[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SetupPath,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedVersion,

    [switch]$SkipUninstall
)

$ErrorActionPreference = "Stop"

if ($env:CI -ne "true" -and $env:TALK_DAT_ALLOW_LOCAL_INSTALLER_SMOKE -ne "1") {
    throw "Installer smoke tests modify the current user's Talk Dat! installation. Run in CI or set TALK_DAT_ALLOW_LOCAL_INSTALLER_SMOKE=1 explicitly."
}

$SetupPath = (Resolve-Path -LiteralPath $SetupPath).Path
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\Talk Dat!"
$AppExe = Join-Path $InstallDir "Talk Dat!.exe"
$UninstallerExe = Join-Path $InstallDir "Talk Dat! Uninstaller.exe"
$ManifestPath = Join-Path $InstallDir "install-manifest.json"
$DataDir = Join-Path $env:APPDATA "TalkDat"
$InstallerLog = Join-Path $DataDir "installer.log"
$RegistryPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\TalkDat"
$MarkerPath = Join-Path $DataDir "ci-installer-smoke-marker.txt"
$Marker = [guid]::NewGuid().ToString("N")

# X-523: what this machine had before the smoke touched it. The smoke ends on
# an uninstall on purpose -- that is how the uninstaller is proven -- but on a
# real machine that last act deletes the app somebody actually dictates with.
# Recorded here, before the first install overwrites the evidence, so the
# restore at the bottom knows whether there is anything to put back.
$PreexistingVersion = if (Test-Path -LiteralPath $AppExe) {
    (Get-Item -LiteralPath $AppExe).VersionInfo.ProductVersion
} else {
    $null
}
$AppWasRunning = [bool](Get-Process -Name "Talk Dat!" -ErrorAction SilentlyContinue)

function Invoke-SilentOperation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$SuccessPattern,

        [Parameter(Mandatory = $true)]
        [string]$FailurePattern
    )

    $Before = if (Test-Path -LiteralPath $InstallerLog) {
        @(Get-Content -LiteralPath $InstallerLog).Count
    } else {
        0
    }

    Start-Process -FilePath $FilePath -ArgumentList $Arguments -WindowStyle Hidden | Out-Null
    $Deadline = (Get-Date).AddMinutes(10)
    do {
        Start-Sleep -Seconds 2
        $NewLines = if (Test-Path -LiteralPath $InstallerLog) {
            @(Get-Content -LiteralPath $InstallerLog | Select-Object -Skip $Before)
        } else {
            @()
        }
        if ($NewLines -match $FailurePattern) {
            throw "Silent operation failed. See $InstallerLog"
        }
        if ($NewLines -match $SuccessPattern) {
            return
        }
    } while ((Get-Date) -lt $Deadline)

    throw "Silent operation timed out. See $InstallerLog"
}

function Assert-InstalledState {
    if (-not (Test-Path -LiteralPath $AppExe)) {
        throw "Installed app is missing: $AppExe"
    }
    if (-not (Test-Path -LiteralPath $UninstallerExe)) {
        throw "Installed uninstaller is missing: $UninstallerExe"
    }
    if (-not (Test-Path -LiteralPath $ManifestPath)) {
        throw "Install manifest is missing: $ManifestPath"
    }

    $Version = (Get-Item -LiteralPath $AppExe).VersionInfo.ProductVersion
    if ($Version -ne $ExpectedVersion) {
        throw "Installed version mismatch. Expected $ExpectedVersion, got $Version."
    }

    if (-not (Test-Path -LiteralPath $RegistryPath)) {
        throw "Windows uninstall registration is missing."
    }
    $RegistryVersion = (Get-ItemProperty -LiteralPath $RegistryPath).DisplayVersion
    if ($RegistryVersion -ne $ExpectedVersion) {
        throw "Registry version mismatch. Expected $ExpectedVersion, got $RegistryVersion."
    }

    $Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if (-not $Manifest.files -or @($Manifest.files).Count -lt 3) {
        throw "Install manifest does not contain the expected payload."
    }
    if ((Get-Content -LiteralPath $MarkerPath -Raw).Trim() -ne $Marker) {
        throw "Private AppData marker was modified during installation."
    }
}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
Set-Content -LiteralPath $MarkerPath -Value $Marker -Encoding ASCII

Write-Output "Installing $ExpectedVersion..."
Invoke-SilentOperation `
    -FilePath $SetupPath `
    -Arguments @("--silent-install", "--no-launch") `
    -SuccessPattern "Silent install completed\." `
    -FailurePattern "Silent install failed:"
Assert-InstalledState

Write-Output "Reinstalling $ExpectedVersion to exercise replacement and AppData preservation..."
Invoke-SilentOperation `
    -FilePath $SetupPath `
    -Arguments @("--silent-install", "--no-launch") `
    -SuccessPattern "Silent install completed\." `
    -FailurePattern "Silent install failed:"
Assert-InstalledState

if (-not $SkipUninstall) {
    Write-Output "Uninstalling $ExpectedVersion..."
    Invoke-SilentOperation `
        -FilePath $UninstallerExe `
        -Arguments @("--silent-uninstall") `
        -SuccessPattern "Silent uninstall completed\." `
        -FailurePattern "Silent uninstall failed:"

    $CleanupDeadline = (Get-Date).AddMinutes(2)
    do {
        Start-Sleep -Seconds 2
    } while (
        ((Test-Path -LiteralPath $AppExe) -or (Test-Path -LiteralPath $RegistryPath)) -and
        (Get-Date) -lt $CleanupDeadline
    )

    if (Test-Path -LiteralPath $AppExe) {
        throw "Installed app remains after silent uninstall."
    }
    if (Test-Path -LiteralPath $RegistryPath) {
        throw "Windows uninstall registration remains after silent uninstall."
    }
    if ((Get-Content -LiteralPath $MarkerPath -Raw).Trim() -ne $Marker) {
        throw "Private AppData marker was removed during default uninstall."
    }
}

# X-523: leave the machine as it was found. A clean CI box had nothing
# installed and stays empty; a machine that had the app gets it back, at the
# version just proven, and started again if it had been running. This runs
# before the marker is removed so the restored install is verified against it
# exactly as the smoke's own installs were.
if ($PreexistingVersion) {
    Write-Output "Restoring the install this machine had before the smoke ($PreexistingVersion -> $ExpectedVersion)..."
    if (-not (Test-Path -LiteralPath $AppExe)) {
        Invoke-SilentOperation `
            -FilePath $SetupPath `
            -Arguments @("--silent-install", "--no-launch") `
            -SuccessPattern "Silent install completed\." `
            -FailurePattern "Silent install failed:"
        Assert-InstalledState
    }
    if ($AppWasRunning) {
        Start-Process -FilePath $AppExe | Out-Null
        Write-Output "Restarted Talk Dat!, which was running before the smoke."
    }
}

Remove-Item -LiteralPath $MarkerPath -Force
Write-Output "Talk Dat! Windows installer smoke test passed for $ExpectedVersion."
