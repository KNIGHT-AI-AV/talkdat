$ErrorActionPreference = "Stop"

$ShortcutPath = Join-Path ([Environment]::GetFolderPath("Startup")) "Talk Dat!.lnk"
if (Test-Path $ShortcutPath) {
    Remove-Item -LiteralPath $ShortcutPath
    Write-Output "Removed startup shortcut:"
    Write-Output $ShortcutPath
} else {
    Write-Output "No Talk Dat! startup shortcut was found."
}
