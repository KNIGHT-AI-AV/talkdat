param(
    [switch]$CreateDesktopShortcut
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $Root ".venv"
$Python = Join-Path $VenvPath "Scripts\python.exe"
# X-108: onedir -- the app is a folder now; the exe lives inside it.
$AppDir = Join-Path $Root "dist\Talk Dat!"
$ExePath = Join-Path $AppDir "Talk Dat!.exe"
$AssetsPath = Join-Path $Root "knight_flow\assets"
$AssetIconPath = Join-Path $AssetsPath "app_icon.ico"
$ShortcutIconPath = Join-Path (Split-Path -Parent $ExePath) "Talk Dat!.ico"
$BuildDir = Join-Path $Root "build"
$VersionInfoPath = Join-Path $BuildDir "talk-dat-version-info.txt"
$RuntimeAssets = @(
    "app_icon.ico",
    "app_icon.png",
    "favicon.ico",
    "favicon.png",
    "flow_pill_240.png",
    "flow_pill_240.json",
    "loading_pill_240.png",
    "loading_pill_240.json",
    "logo.ico",
    "logo.png",
    "license_public_key.pem"
)
$RuntimeUiAssets = @(
    "flow-console-material.png",
    "processing-spectrum-loop-4k.png"
)
$RuntimeOnboardingAssets = @(
    "01-arrival-stone.png",
    "02-access-continuity.png",
    "03-route-engine.png",
    "04-voice-instrument.png",
    "05-command-deck.png",
    "06-finish-engine.png"
)

function Test-UsablePython {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $false }
    try {
        & $Path --version *> $null
        if ($LASTEXITCODE -ne 0) { return $false }
        & $Path -m pip --version *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Invoke-Checked {
    param(
        [string]$Label,
        [scriptblock]$Script
    )
    & $Script
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Assert-FilesExist {
    param(
        [string]$BasePath,
        [string[]]$Names,
        [string]$Label
    )
    foreach ($Name in $Names) {
        $Path = Join-Path $BasePath $Name
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "Missing required $Label asset: $Path"
        }
    }
}

function New-VersionInfoFile {
    param(
        [string]$Path,
        [string]$Version,
        [string]$FileDescription
    )
    $VersionParts = [regex]::Matches($Version, "\d+") | ForEach-Object { [int]$_.Value }
    $Numbers = @(0, 0, 0, 0)
    for ($Index = 0; $Index -lt [Math]::Min(4, $VersionParts.Count); $Index++) {
        $Numbers[$Index] = $VersionParts[$Index]
    }
    $NumericVersion = "$($Numbers[0]).$($Numbers[1]).$($Numbers[2]).$($Numbers[3])"
    $Text = @"
# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($($Numbers[0]), $($Numbers[1]), $($Numbers[2]), $($Numbers[3])),
    prodvers=($($Numbers[0]), $($Numbers[1]), $($Numbers[2]), $($Numbers[3])),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904b0', [
        StringStruct('CompanyName', 'Knight AI+AV'),
        StringStruct('FileDescription', '$FileDescription'),
        StringStruct('FileVersion', '$NumericVersion'),
        StringStruct('InternalName', 'Talk Dat!'),
        StringStruct('OriginalFilename', 'Talk Dat!.exe'),
        StringStruct('ProductName', 'Talk Dat!'),
        StringStruct('ProductVersion', '$Version')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    Set-Content -LiteralPath $Path -Value $Text -Encoding UTF8
}

if (-not (Test-UsablePython $Python)) {
    if (Test-Path $VenvPath) {
        $ResolvedRoot = (Resolve-Path $Root).Path
        $ResolvedVenv = (Resolve-Path $VenvPath).Path
        if (-not $ResolvedVenv.StartsWith($ResolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove virtualenv outside repo: $ResolvedVenv"
        }
        Remove-Item -LiteralPath $ResolvedVenv -Recurse -Force
    }
    $Uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($Uv) {
        if (-not $env:UV_CACHE_DIR) {
            $env:UV_CACHE_DIR = Join-Path $Root ".uv-cache"
        }
        if (-not $env:UV_PYTHON_INSTALL_DIR) {
            $env:UV_PYTHON_INSTALL_DIR = Join-Path $Root ".uv-python"
        }
        Invoke-Checked "uv venv" { & $Uv.Source venv --seed $VenvPath }
    } else {
        Invoke-Checked "python venv" { python -m venv $VenvPath }
    }
}

if (-not (Test-UsablePython $Python)) {
    throw "Could not create a usable Python virtualenv at $VenvPath"
}

Invoke-Checked "pip upgrade" { & $Python -m pip install --upgrade pip }
# X-230: install from the LOCK, not the ranges.
#
# requirements.txt is entirely ranges: websockets>=14.0, numpy>=1.26, and so
# on, with no upper bound on most and no pin on any transitive dependency. So
# every build of the SIGNED binary pulled whatever PyPI happened to serve that
# minute, and two builds of the same commit could contain different code. A
# compromised or merely broken upstream release would land inside a binary
# carrying Knight AI+AV's Authenticode signature, which is the strongest claim
# this project makes about a file.
#
# requirements.lock pins every package, direct and transitive, to an exact
# version AND a set of SHA-256 hashes. pip verifies each hash before it
# installs, so a substituted artifact fails the build instead of shipping.
#
# Regenerate deliberately, never casually:
#     uv pip compile requirements.txt --generate-hashes --output-file requirements.lock
# X-408: --no-deps, because the lock is the complete transitive set already and the
# resolver would otherwise insist on the CPU onnxruntime that faster-whisper and
# openwakeword name, which the lock excludes on Windows in favour of DirectML.
Invoke-Checked "requirements install" { & $Python -m pip install --require-hashes --no-deps -r (Join-Path $Root "requirements.lock") }
# X-408: the DirectML build of onnxruntime must be the one that lands. faster-whisper
# and openwakeword ask for plain onnxruntime, so the lock carries both wheels and
# they overwrite each other's files in whatever order pip chose. Reinstalling the
# DirectML wheel last, without its dependencies, settles it; the check after it
# fails the build rather than shipping a CPU-only runtime by accident.
$DirectMlPin = (Get-Content (Join-Path $Root "requirements.lock")) | Where-Object { $_ -match "^onnxruntime-directml==" } | ForEach-Object { ($_ -split "\s")[0] } | Select-Object -First 1
if (-not $DirectMlPin) { throw "requirements.lock has no onnxruntime-directml pin" }
Invoke-Checked "directml runtime" { & $Python -m pip install --force-reinstall --no-deps $DirectMlPin }
Invoke-Checked "directml present" { & $Python -c "import onnxruntime as o, sys; sys.exit(0 if 'DmlExecutionProvider' in o.get_available_providers() else 1)" }
Invoke-Checked "pyinstaller install" { & $Python -m pip install pyinstaller }

$IconPath = $AssetIconPath
if (-not (Test-Path $IconPath)) {
    $IconPath = (& $Python -c "from knight_flow.icon import ensure_icon_file; print(ensure_icon_file())").Trim()
}

$AppVersion = (& $Python -c "from knight_flow.version import APP_VERSION; print(APP_VERSION)").Trim()
New-VersionInfoFile -Path $VersionInfoPath -Version $AppVersion -FileDescription "Talk Dat! dictation overlay"

# The app is built from the CURATED spec, never from CLI arguments.
# A CLI invocation regenerates "Talk Dat!.spec" in place, and on 2026-08-08
# that silently destroyed the hand-written spec -- dropping the cryptography
# collection (the 0.4.38 crash-on-launch bug) and the generated version
# resource. The spec carries every flag that used to live here: onefile,
# windowed, icon, version resource, asset datas, and the scipy/sklearn/cv2
# exclusions with their measurements. Edit the spec, not this file.
$SpecPath = Join-Path $Root "Talk Dat!.spec"
if (-not (Test-Path $SpecPath)) { throw "Missing curated spec: $SpecPath" }
$OnboardingAssetsPath = Join-Path $AssetsPath "onboarding"
Assert-FilesExist -BasePath $OnboardingAssetsPath -Names $RuntimeOnboardingAssets -Label "onboarding source"
# Open source (2026-09-23): OFFICIAL or SOURCE is decided here and baked into
# knight_flow/_build_flags.py, which only an official build uses to reach
# Knight AI+AV's services (sign-in, counts, feedback, prefs, update check).
# The generated module is deleted again afterwards so the working tree stays
# clean; build\talk-dat-build-flags.json keeps the receipt publish_release.py
# checks. See knight_flow/official_build.py and docs/NETWORK.md.
$BuildFlagsScript = Join-Path $Root "scripts\write_build_flags.py"
Invoke-Checked "build flags" { & $Python $BuildFlagsScript }
try {
    Invoke-Checked "pyinstaller build" { & $Python -m PyInstaller "$SpecPath" --noconfirm --clean }
} finally {
    & $Python $BuildFlagsScript --clean
}

# Every third-party component in the payload, with its license text, generated
# from the bundled packages' own metadata. --strict fails the build when a
# bundled package has no license that can be resolved.
$ThirdPartyLicenses = Join-Path $AppDir "THIRD_PARTY_LICENSES.txt"
$AnalysisToc = Join-Path $BuildDir "Talk Dat!\Analysis-00.toc"
Invoke-Checked "third-party licenses" { & $Python (Join-Path $Root "scripts\collect_licenses.py") --bundle "$AppDir" --analysis "$AnalysisToc" --spec "$SpecPath" --output "$ThirdPartyLicenses" --strict }
Copy-Item -LiteralPath (Join-Path $Root "LICENSE") -Destination (Join-Path $AppDir "LICENSE.txt") -Force
Copy-Item -LiteralPath (Join-Path $Root "NOTICE") -Destination (Join-Path $AppDir "NOTICE.txt") -Force

$PackagedOnboardingCandidates = @(
    (Join-Path $AppDir "_internal\knight_flow\assets\onboarding"),
    (Join-Path $AppDir "knight_flow\assets\onboarding")
)
$PackagedOnboardingPath = $PackagedOnboardingCandidates |
    Where-Object { Test-Path -LiteralPath $_ -PathType Container } |
    Select-Object -First 1
if (-not $PackagedOnboardingPath) {
    throw "Packaged onboarding assets directory is missing: $($PackagedOnboardingCandidates -join ', ')"
}
Assert-FilesExist -BasePath $PackagedOnboardingPath -Names $RuntimeOnboardingAssets -Label "packaged onboarding"

Copy-Item $IconPath $ShortcutIconPath -Force

Write-Output "Built:"
Write-Output $ExePath
Write-Output "Shortcut icon:"
Write-Output $ShortcutIconPath

if ($CreateDesktopShortcut) {
    $Desktop = [Environment]::GetFolderPath("Desktop")
    $ShortcutPath = Join-Path $Desktop "Talk Dat!.lnk"
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $ExePath
    $Shortcut.WorkingDirectory = Split-Path -Parent $ExePath
    $Shortcut.IconLocation = "$ShortcutIconPath,0"
    $Shortcut.Description = "Launch Talk Dat! dictation overlay."
    $Shortcut.Save()
    Write-Output "Desktop shortcut:"
    Write-Output $ShortcutPath
}
