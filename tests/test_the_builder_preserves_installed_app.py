"""Execute the builder's cleanup against fake processes and a fake filesystem."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'win32', 'Windows release builder')
class BuildCleanupTests(unittest.TestCase):
    def cleanup(self, skip=False):
        source = (ROOT / 'build-custom-installer.ps1').read_text(encoding='utf-8')
        # Select the actual cleanup statement, without executing the builder.
        # Both the old and fixed forms begin at this comment.
        start = source.index('# A running instance')
        end = source.index('# End build-payload cleanup', start) if '# End build-payload cleanup' in source else source.index('$ProvidersDoc', start)
        cleanup = source[start:end]
        harness = r'''
$ErrorActionPreference = 'Stop'
$Root = 'C:\synthetic-talkdat-repo'
$AppDir = Join-Path $Root 'dist\Talk Dat!'
$AppExe = Join-Path $AppDir 'Talk Dat!.exe'
$script:stopped = @()
$script:removed = @()
function Get-Process {
    [pscustomobject]@{Id=11;Path='C:\Users\Fixture\AppData\Local\Programs\Talk Dat!\Talk Dat!.exe'}
    [pscustomobject]@{Id=12;Path=$AppExe}
    [pscustomobject]@{Id=13;Path='C:\synthetic-talkdat-repo-other\dist\Talk Dat!\Talk Dat!.exe'}
    [pscustomobject]@{Id=14;Path=$null}
}
function Stop-Process {
    param([Parameter(ValueFromPipeline=$true)]$InputObject, [switch]$Force)
    process {$script:stopped += $InputObject.Id}
}
function Start-Sleep {param($Seconds)}
function Test-Path {param($LiteralPath, $Path); return $true}
function Resolve-Path {param($LiteralPath, $Path); [pscustomobject]@{Path=($LiteralPath+$Path)}}
function Get-Item {param($LiteralPath); [pscustomobject]@{Attributes=[IO.FileAttributes]::Directory}}
function Remove-Item {param($LiteralPath,[switch]$Recurse,[switch]$Force); $script:removed += $LiteralPath}
'''
        harness += '\n$SkipExeBuild = $' + str(skip).lower() + '\n' + cleanup
        harness += '\nConvertTo-Json -Compress @{stopped=@($script:stopped);removed=@($script:removed)}\n'
        result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', '-'],
                                input=harness, text=True, capture_output=True, timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout.strip())

    def test_cleanup_stops_only_the_exact_build_payload(self):
        actual = self.cleanup()
        self.assertEqual(actual['stopped'], [12])
        self.assertEqual(actual['removed'], [r'C:\synthetic-talkdat-repo\dist\Talk Dat!'])

    def test_skip_build_does_not_stop_or_delete_anything(self):
        self.assertEqual(self.cleanup(skip=True), {'stopped': [], 'removed': []})

    def test_cleanup_happens_after_the_build_mutex_is_acquired(self):
        source = (ROOT / 'build-custom-installer.ps1').read_text(encoding='utf-8')
        self.assertLess(source.index('if (-not $HasBuildMutex)'), source.index('# A running instance'))
