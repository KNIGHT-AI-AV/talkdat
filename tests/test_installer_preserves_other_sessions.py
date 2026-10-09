"""Run the installer stop script with synthetic processes and no native actions."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from installer import glass_installer as installer

OTHER_ACCOUNT_REFUSAL = "Talk DAT! is open in another Windows account. Close it there, then try again."


@unittest.skipUnless(sys.platform == "win32", "PowerShell stop-policy fixture")
class InstallerProcessOwnershipTests(unittest.TestCase):
    def script(self, profile: str = r"C:\fixture") -> str:
        # The fixture install folder sits inside this profile unless a test
        # names another one, the way a default per-user install does.
        with patch.object(installer, "run_powershell") as run, \
                patch.dict(os.environ, {"USERPROFILE": profile}):
            installer.stop_running_app(Path(r"C:\fixture\Talk Dat!"))
        return run.call_args.args[0]

    def exercise(self, case: str, profile: str = r"C:\fixture") -> dict:
        # Only these two native current-process boundaries are replaced. All
        # process enumeration, handles, termination and waiting are fake below.
        code = self.script(profile).replace(
            "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value",
            "'fixture-owner'",
        ).replace(
            "[System.Diagnostics.Process]::GetCurrentProcess().SessionId", "5"
        )
        harness = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$env:WINDIR = 'C:\fixture-windows'
$global:stopped = @()
$global:broad = @()
$global:disposed = @()
$global:handleReads = @()
$global:rows = @()
$global:freshReads = 0
$global:clockReads = 0
$stamp = [datetime]'2026-10-08T01:00:00Z'
function New-FakeProcess($id, $name, $path, $session=5, $sid='fixture-owner') {
  $row = [pscustomobject]@{ProcessId=$id; Name=$name; ExecutablePath=$path;
    SessionId=$session; Sid=$sid; CreationDate=$stamp; Alive=$true}
  $global:rows += $row
}
New-FakeProcess 111 'Talk Dat!.exe' 'C:\fixture\Talk Dat!\Talk Dat!.exe'
New-FakeProcess 112 'Talk Dat!.exe' 'C:\fixture\Talk Dat!-other\Talk Dat!.exe'
New-FakeProcess 114 'Knight Flow.exe' 'C:\other\Knight Flow.exe'
if ($case -eq 'foreign-session') {
  New-FakeProcess 113 'Talk Dat!.exe' 'C:\fixture\Talk Dat!\Talk Dat!.exe' 9
}
if ($case -eq 'foreign-owner') {
  New-FakeProcess 113 'Talk Dat!.exe' 'C:\fixture\Talk Dat!\Talk Dat!.exe' 5 'other-owner'
}
if ($case -eq 'unknown-path') {
  New-FakeProcess 115 'Talk Dat!.exe' $null
}
# Another Windows account's copy: without elevation its path is unreadable.
if ($case -eq 'other-account') {
  New-FakeProcess 117 'Talk Dat!.exe' $null 9 'other-account'
}
if ($case -eq 'unknown-owner') { $global:rows[0].Sid = $null }
if ($case -eq 'missing-creation') { $global:rows[0].CreationDate = $null }
if ($case -eq 'legacy') {
  New-FakeProcess 116 'Knight Flow.exe' 'C:\fixture\Talk Dat!\Knight Flow.exe'
}
function Get-CimInstance {
  param($ClassName, $Filter)
  if ($Filter -match 'ProcessId\s*=\s*(\d+)') {
    $global:freshReads++
    $row = $global:rows | Where-Object ProcessId -eq ([int]$matches[1])
    if ($case -eq 'reused-pid') {
      $copy = $row.PSObject.Copy()
      $copy.CreationDate = $stamp.AddSeconds(10)
      return $copy
    }
    if ($case -in @('changed-path', 'changed-owner', 'changed-session')) {
      $copy = $row.PSObject.Copy()
      if ($case -eq 'changed-path') { $copy.ExecutablePath = 'C:\other\Talk Dat!.exe' }
      if ($case -eq 'changed-owner') { $copy.Sid = 'other-owner' }
      if ($case -eq 'changed-session') { $copy.SessionId = 9 }
      return $copy
    }
    return $row
  }
  $global:rows | Where-Object Alive
}
function Invoke-CimMethod {
  param($InputObject, $MethodName)
  if (-not $InputObject.Sid) { throw 'Owner unreadable' }
  [pscustomobject]@{ReturnValue=0; Sid=$InputObject.Sid}
}
function Get-Process {
  param($Id, $ErrorAction)
  $row = $global:rows | Where-Object ProcessId -eq $Id
  $obj = [pscustomobject]@{Id=$row.ProcessId; SessionId=$row.SessionId}
  $obj | Add-Member ScriptProperty HasExited { -not ($global:rows | Where-Object ProcessId -eq $this.Id).Alive }
  $obj | Add-Member ScriptProperty Handle {
    $global:handleReads += $this.Id
    if ($case -eq 'unreadable-handle') { throw 'Handle unavailable' }
    if ($case -eq 'zero-handle') { return 0 }
    123
  }
  $obj | Add-Member ScriptMethod Kill {
    $global:stopped += $this.Id
    if ($case -ne 'timeout') {
      ($global:rows | Where-Object ProcessId -eq $this.Id).Alive = $false
    }
    if ($case -eq 'restart') {
      New-FakeProcess 119 'Talk Dat!.exe' 'C:\fixture\Talk Dat!\Talk Dat!.exe'
    }
  }
  $obj | Add-Member ScriptMethod WaitForExit { param($ms) $case -ne 'timeout' }
  $obj | Add-Member ScriptMethod Dispose { $global:disposed += $this.Id }
  $obj
}
function Stop-Process { param($Id, [switch]$Force, $ErrorAction) $global:stopped += $Id }
function Start-Sleep { param($Milliseconds, $Seconds) }
function Get-Date { $global:clockReads++; $stamp.AddSeconds($global:clockReads * 10) }
function Test-Path { param($LiteralPath, $Path) $true }
function Record-BroadStop { param([Parameter(ValueFromRemainingArguments=$true)]$args) $global:broad += 'name-wide-stop' }
Set-Alias -Name 'C:\fixture-windows\System32\taskkill.exe' -Value Record-BroadStop
Set-Alias -Name 'C:\fixture-windows\System32\\taskkill.exe' -Value Record-BroadStop
$failed = $false
$message = $null
try {
'''
        harness = harness.replace("Knight Flow.exe", installer.LEGACY_APP_EXE_NAME)
        harness = "$case = '" + case + "'\n" + harness + code + r'''
} catch { $failed = $true; $message = $_.Exception.Message }
ConvertTo-Json -Compress @{stopped=@($global:stopped);broad=@($global:broad);
  failed=$failed;message=$message;disposed=@($global:disposed);handles=@($global:handleReads)}
'''
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
             base64.b64encode(harness.encode("utf-16-le")).decode("ascii")],
            text=True, capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env={**os.environ, "WINDIR": r"C:\fixture-windows"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(result.stderr.strip(), result.stderr)
        return json.loads(result.stdout.strip())

    def test_only_exact_current_user_session_install_is_stopped(self):
        result = self.exercise("normal")
        self.assertEqual(result["stopped"], [111])
        self.assertEqual(result["broad"], [])
        self.assertFalse(result["failed"])
        self.assertEqual(result["handles"], [111])
        self.assertEqual(result["disposed"], [111])

    def test_legacy_name_must_belong_to_the_same_install(self):
        result = self.exercise("legacy")
        self.assertEqual(result["stopped"], [111, 116])
        self.assertEqual(result["broad"], [])
        self.assertFalse(result["failed"])

    def test_uncertain_or_foreign_ownership_refuses_before_any_stop(self):
        for case in ("foreign-session", "foreign-owner", "unknown-path",
                     "unknown-owner", "missing-creation", "reused-pid",
                     "changed-path", "changed-owner", "changed-session",
                     "unreadable-handle", "zero-handle"):
            with self.subTest(case=case):
                result = self.exercise(case)
                self.assertEqual(result["stopped"], [])
                self.assertEqual(result["broad"], [])
                self.assertTrue(result["failed"])

    def test_another_accounts_copy_does_not_block_a_private_install(self):
        # 2026-10-08: this PC has a second signed-in account, and every one of
        # its processes reads back with no path. Another account cannot run
        # programs inside this user's profile, so its copy is left alone.
        result = self.exercise("other-account")
        self.assertEqual(result["stopped"], [111])
        self.assertEqual(result["broad"], [])
        self.assertFalse(result["failed"], result["message"])

    def test_another_accounts_copy_blocks_a_shared_install_folder(self):
        # Outside the profile another account may be running this very
        # folder, and its path cannot be read to rule that out.
        result = self.exercise("other-account", profile=r"C:\Users\fixture-user")
        self.assertEqual(result["stopped"], [])
        self.assertEqual(result["broad"], [])
        self.assertTrue(result["failed"])
        self.assertEqual(result["message"], OTHER_ACCOUNT_REFUSAL)

    def test_new_process_after_snapshot_is_not_adopted_or_stopped(self):
        result = self.exercise("restart")
        self.assertEqual(result["stopped"], [111])
        self.assertEqual(result["broad"], [])
        self.assertTrue(result["failed"])

    def test_unfinished_stop_refuses_commit_and_releases_handle(self):
        result = self.exercise("timeout")
        self.assertEqual(result["stopped"], [111])
        self.assertTrue(result["failed"])
        self.assertEqual(result["disposed"], [111])

    def test_stop_failure_reaches_the_install_transaction(self):
        with patch.object(installer, "run_powershell", side_effect=RuntimeError("cannot establish owner")):
            with self.assertRaises(RuntimeError):
                installer.stop_running_app(Path(r"C:\fixture\Talk Dat!"))

    def test_stop_refusal_preserves_existing_install_before_commit(self):
        with tempfile.TemporaryDirectory(prefix="talkdat-owner-fixture-") as temporary:
            root = Path(temporary)
            installed = root / "installed"
            installed.mkdir()
            old_app = installed / installer.APP_EXE_NAME
            old_app.write_bytes(b"old app fixture")
            manifest = installed / installer.MANIFEST_NAME
            manifest.write_text(json.dumps({"files": [str(old_app)]}), encoding="utf-8")
            manifest_before = manifest.read_bytes()
            payload = root / "payload/app"
            payload.mkdir(parents=True)
            (payload / installer.APP_EXE_NAME).write_bytes(b"new app fixture")
            uninstaller = root / "new-uninstaller.exe"
            uninstaller.write_bytes(b"uninstaller fixture")
            with (
                patch.object(installer, "resource_path", side_effect=lambda *parts: root.joinpath(*parts)),
                patch.object(installer, "payload_path", return_value=uninstaller),
                patch.object(installer, "run_powershell", side_effect=RuntimeError("owner uncertain")),
                patch.object(installer, "migrate_legacy_user_data") as migrate,
                patch.object(installer, "register_uninstaller") as register,
                patch.object(installer, "remove_shortcut"),
            ):
                with self.assertRaises(RuntimeError):
                    installer.install_app({"install_dir": installed, "start_menu": False,
                                           "desktop": False, "startup": False, "launch": False},
                                          lambda *_: None)
                migrate.assert_not_called()
                register.assert_not_called()
            self.assertEqual(old_app.read_bytes(), b"old app fixture")
            self.assertEqual(manifest.read_bytes(), manifest_before)
            self.assertEqual(list(root.glob(".installed-update-*")), [])

    def test_uninstall_refusal_keeps_the_app_and_its_registration(self):
        with (
            patch.object(installer, "installed_location", return_value=Path(r"C:\fixture\Talk Dat!")),
            patch.object(installer, "load_manifest", return_value={"files": [], "shortcuts": []}),
            patch.object(installer, "run_powershell", side_effect=RuntimeError("owner uncertain")),
            patch.object(installer, "remove_shortcut") as remove_shortcut,
            patch.object(installer, "safe_delete_file") as delete_file,
            patch.object(installer, "unregister_uninstaller") as unregister,
        ):
            with self.assertRaises(RuntimeError):
                installer.uninstall_app({"remove_shortcuts": True}, lambda *_: None)
        remove_shortcut.assert_not_called()
        delete_file.assert_not_called()
        unregister.assert_not_called()


@unittest.skipUnless(sys.platform == "win32", "PowerShell refusal text")
class InstallerRefusalTextTests(unittest.TestCase):
    """Run two tiny PowerShell scripts that read and change nothing."""

    def test_refusal_reaches_the_installer_window_as_one_sentence(self):
        # The window shows str(error). Before the fix it carried PowerShell's
        # whole error record: script position, a caret line, category and id.
        sentence = "Cannot identify a running Talk DAT! copy. Quit it, then try again."
        with self.assertRaises(RuntimeError) as caught:
            installer.run_powershell("try { throw '" + sentence + "' } finally { $null = 1 }")
        self.assertEqual(str(caught.exception), sentence)

    def test_a_script_that_succeeds_raises_nothing(self):
        installer.run_powershell("$null = 1")


if __name__ == "__main__":
    unittest.main()
