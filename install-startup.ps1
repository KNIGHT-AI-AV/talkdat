$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ExePath = Join-Path $Root "dist\Talk Dat!.exe"
$RunScript = Join-Path $Root "run.ps1"
$Startup = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $Startup "Talk Dat!.lnk"
$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path $RunScript) -and -not (Test-Path $ExePath)) {
    throw "Missing run script: $RunScript"
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
if (Test-Path $ExePath) {
    $Shortcut.TargetPath = $ExePath
    $Shortcut.Arguments = ""
    $Shortcut.WorkingDirectory = Split-Path -Parent $ExePath
    $Shortcut.WindowStyle = 1
    $Shortcut.IconLocation = "$ExePath,0"
} else {
    $Shortcut.TargetPath = $PowerShell
    $Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunScript`""
    $Shortcut.WorkingDirectory = $Root
    $Shortcut.WindowStyle = 7
    $Shortcut.IconLocation = "$PowerShell,0"
}
$Shortcut.Description = "Start Talk Dat! dictation overlay when Windows signs in."
$Shortcut.Save()

Write-Output "Talk Dat! will start when you sign in:"
Write-Output $ShortcutPath
