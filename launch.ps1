$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ExePath = Join-Path $Root "dist\Talk Dat!.exe"
$RunScript = Join-Path $Root "run.ps1"
$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if (Test-Path $ExePath) {
    Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path -Parent $ExePath)
} else {
    Start-Process `
        -FilePath $PowerShell `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$RunScript`"" `
        -WorkingDirectory $Root `
        -WindowStyle Hidden
}

Write-Output "Talk Dat! launched."
