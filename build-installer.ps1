param(
    [switch]$SkipExeBuild
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$CustomBuilder = Join-Path $Root "build-custom-installer.ps1"

& $CustomBuilder -SkipExeBuild:$SkipExeBuild
