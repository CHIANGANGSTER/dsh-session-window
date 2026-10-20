<#
.SYNOPSIS
    Install the R2 patched DSH Desktop shell (B-06).

.DESCRIPTION
    Replaces <AppDir>\resources\app.asar with the patched build recorded in the
    frozen MANIFEST, after proving the current file is the pristine BASELINE and
    the target is authorised. Every step is bounded by an explicit hash; the whole
    change is reversible through the transaction it writes.

    Design rules this tool obeys
      * It never terminates a process. It waits for the app and Host to exit.
      * It refuses to run when it was itself started from inside <AppDir>
        (exit 2) - the R2.5 ancestor guard.
      * The formal installation directory always needs an authorisation file
        whose patched_sha256 and manifest_sha256 both match (exit 7).
      * The replacement goes through [System.IO.File]::Replace only; the target is
        never removed or copy-overwritten.
      * A PREPARED transaction is written before the swap, then COMMITTED, or
        ROLLED_BACK after an automatic restore from the verified backup.

    ASCII-only on purpose: PowerShell 5.1 decodes a BOM-less UTF-8 script as the
    system ANSI code page. Chinese lives in the operation cards.

.PARAMETER AppDir
    Installation directory containing resources\app.asar.

.PARAMETER Manifest
    Frozen build manifest. Defaults to $R2\MANIFEST.json.

.PARAMETER RequireAuthorization
    Force the authorisation check even for a non-formal AppDir.

.PARAMETER AuthorizationFile
    Authorisation file for self tests. The formal directory always uses
    $R2\AUTHORIZATION.json and ignores this parameter.

.PARAMETER WhatIf
    Report every step without changing anything.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -WhatIf
#>
[CmdletBinding()]
param(
    [string]$AppDir = "E:\Software\DeepSeek Harness",
    [string]$Manifest,
    [switch]$RequireAuthorization,
    [string]$AuthorizationFile,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

# Resolve the kit root by walking up until a directory contains log.ps1 and
# work\r2. install.ps1/rollback.ps1 sit AT the kit root while
# rollback-plugin.ps1 sits three levels down in work\r2\build, so counting
# parent directories is not portable (getting it wrong made every exit code 1).
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$kit = $null
$probe = Get-Item -LiteralPath $scriptDir
for ($depth = 0; $depth -lt 6 -and $probe; $depth++) {
    if ((Test-Path -LiteralPath (Join-Path $probe.FullName "log.ps1")) -and
        (Test-Path -LiteralPath (Join-Path $probe.FullName "work\r2"))) { $kit = $probe.FullName; break }
    $probe = $probe.Parent
}
if (-not $kit) { throw "cannot locate the kit root from $scriptDir" }
$r2 = Join-Path $kit "work\r2"
if (-not $Manifest) { $Manifest = Join-Path $r2 "MANIFEST.json" }
if (-not $AuthorizationFile) { $AuthorizationFile = Join-Path $r2 "AUTHORIZATION.json" }

$evidence = Join-Path $r2 "evidence"
$txDir = Join-Path $r2 "tx"
New-Item -ItemType Directory -Force $evidence, $txDir | Out-Null
$log = Join-Path $evidence ("B-06-install-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")

. (Join-Path $kit "log.ps1")

function Exit-With([int]$code) { exit $code }

Write-R2Log "install: start" info $log
Write-R2Log "app dir  : $AppDir" info $log
Write-R2Log "manifest : $Manifest" info $log

# ── 1. manifest ──────────────────────────────────────────────────────────────
try { $mf = Test-R2Manifest -Path $Manifest } catch { Write-R2Log $_ err $log; Exit-With 7 }
$baseline = "$($mf.baseline_sha256)".ToLower()
$patched = "$($mf.patched_sha256)".ToLower()
$formal = [System.IO.Path]::GetFullPath("$($mf.formal_app_dir)").TrimEnd("\")
$isFormal = ([System.IO.Path]::GetFullPath($AppDir).TrimEnd("\")) -ieq $formal
$envName = if ($isFormal) { "formal" } else { (Split-Path -Leaf ([System.IO.Path]::GetFullPath($AppDir).TrimEnd("\"))) }
Write-R2Log "baseline : $baseline" info $log
Write-R2Log "patched  : $patched" info $log
Write-R2Log "formal   : $formal   (this run: $(if ($isFormal) { 'FORMAL' } else { 'self test: ' + $envName }))" info $log

$target = Join-Path $AppDir "resources\app.asar"
$patchedSource = Join-Path $r2 "build\pkg\app.asar"
if (-not (Test-Path -LiteralPath $patchedSource)) { Write-R2Log "patched build missing: $patchedSource" err $log; Exit-With 3 }

# ── 2. ancestor guard ────────────────────────────────────────────────────────
$inside = @(Test-R2InsideDir -Directory $AppDir)
if ($inside.Count -gt 0) {
    Write-R2Log "started from inside the target directory - refuse (exit 2)" err $log
    foreach ($proc in $inside) { Write-R2Log ("  ancestor pid {0} {1}" -f $proc.ProcessId, $proc.ExecutablePath) info $log }
    Write-R2Log "launch this from the Explorer window instead" warn $log
    Exit-With 2
}

# ── 3. authorisation ─────────────────────────────────────────────────────────
if ($isFormal -or $RequireAuthorization) {
    $authPath = if ($isFormal) { Join-Path $r2 "AUTHORIZATION.json" } else { $AuthorizationFile }
    if (-not (Test-Path -LiteralPath $authPath)) {
        Write-R2Log "authorisation file missing: $authPath (exit 7)" err $log
        Exit-With 7
    }
    $auth = Get-Content -LiteralPath $authPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $manifestHash = (Get-R2Sha256 -Path $Manifest).ToLower()
    if ("$($auth.patched_sha256)".ToLower() -ne $patched) {
        Write-R2Log "authorisation patched_sha256 mismatch (exit 7)" err $log
        Exit-With 7
    }
    if ("$($auth.manifest_sha256)".ToLower() -ne $manifestHash) {
        Write-R2Log "authorisation manifest_sha256 mismatch (exit 7)  expected $manifestHash" err $log
        Exit-With 7
    }
    Write-R2Log "authorisation verified against $authPath" ok $log
}

# ── 4. state ─────────────────────────────────────────────────────────────────
if (-not (Test-Path -LiteralPath $target)) { Write-R2Log "target not found: $target (exit 3)" err $log; Exit-With 3 }
$current = (Get-R2Sha256 -Path $target).ToLower()
Write-R2Log "current  : $current  ($((Get-Item -LiteralPath $target).Length.ToString('N0')) B)" info $log
if ($current -eq $patched) { Write-R2Log "already installed - nothing to do" ok $log; Exit-With 0 }
if ($current -ne $baseline) { Write-R2Log "unknown state - refusing to touch it (exit 3)" err $log; Exit-With 3 }

if ($WhatIf) {
    Write-R2Log "WhatIf: would back up, stage $patchedSource, then File.Replace" warn $log
    Write-R2Log "WhatIf: no change made" warn $log
    Exit-With 0
}

# ── 5. wait for the app and the Host to exit ─────────────────────────────────
Write-R2Log "waiting for processes under the app dir (max 120 s)" info $log
$hostNames = @()
if ($mf.host_process_names) { $hostNames = @($mf.host_process_names) }
if (-not (Wait-R2Exited -Directory $AppDir -TimeoutSeconds 120 -ExtraNames $hostNames -LogPath $log)) {
    Write-R2Log "app or Host still running (exit 5)" err $log
    Write-R2Log "quit DeepSeek Harness from the tray, confirm it is gone, then retry" warn $log
    Exit-With 5
}
Write-R2Log "app stopped - nothing left under the app dir" ok $log

# ── 6. transaction id + backup ───────────────────────────────────────────────
$txid = New-R2TxId
$resourcesDir = Split-Path -Parent $target
$backupInPlace = Join-Path $resourcesDir "app.asar.original-$txid"
$backupR2Dir = Join-Path $r2 "backup\$envName"
New-Item -ItemType Directory -Force $backupR2Dir | Out-Null
$backupR2 = Join-Path $backupR2Dir "app.asar.original-$txid"

Copy-Item -LiteralPath $target -Destination $backupInPlace -Force
Copy-Item -LiteralPath $target -Destination $backupR2 -Force
foreach ($copy in @($backupInPlace, $backupR2)) {
    $hash = (Get-R2Sha256 -Path $copy).ToLower()
    if ($hash -ne $baseline) { Write-R2Log "backup hash mismatch at $copy (exit 3)" err $log; Exit-With 3 }
}
Write-R2Log "backed up to $backupInPlace and $backupR2" ok $log

# ── 7. stage ─────────────────────────────────────────────────────────────────
$staging = Join-Path $resourcesDir "app.asar.r2-staging-$txid"
Copy-Item -LiteralPath $patchedSource -Destination $staging -Force
$stageHash = (Get-R2Sha256 -Path $staging).ToLower()
if ($stageHash -ne $patched) {
    Write-R2Log "staging hash mismatch (exit 3)" err $log
    Remove-Item -LiteralPath $staging -Force -ErrorAction SilentlyContinue
    Exit-With 3
}
Write-R2Log "staged $staging ($stageHash)" ok $log

$txRecord = Join-Path $txDir ("install-$txid.json")
$record = [ordered]@{
    txid            = $txid
    tool            = "install"
    started_at      = (Get-Date).ToString("o")
    app_dir         = [System.IO.Path]::GetFullPath($AppDir)
    is_formal       = $isFormal
    env_name        = $envName
    baseline_sha256 = $baseline
    patched_sha256  = $patched
    before_sha256   = $current
    backup_in_place = $backupInPlace
    backup_r2       = $backupR2
    manifest        = [System.IO.Path]::GetFullPath($Manifest)
    state           = "PREPARED"
}
Write-R2Json -Path $txRecord -Value $record
Write-R2Log "tx PREPARED: $txRecord" ok $log

# ── 8. swap, then verify, then (on failure) restore ──────────────────────────
try {
    Replace-R2File -Source $staging -Destination $target
} catch {
    Write-R2Log "replace failed: $_" err $log
    Remove-Item -LiteralPath $staging -Force -ErrorAction SilentlyContinue
    Exit-With 6
}
$after = (Get-R2Sha256 -Path $target).ToLower()
if ($after -ne $patched) {
    Write-R2Log "post-replace verification failed - restoring the backup" err $log
    $restore = Join-Path $resourcesDir "app.asar.r2-restore-$txid"
    Copy-Item -LiteralPath $backupR2 -Destination $restore -Force
    try {
        Replace-R2File -Source $restore -Destination $target
    } catch {
        $record.state = "NEEDS_RECOVERY"
        Write-R2Json -Path $txRecord -Value $record
        Write-R2Log "restore failed too (exit 6)" err $log
        Exit-With 6
    }
    $final = (Get-R2Sha256 -Path $target).ToLower()
    $record.state = if ($final -eq $baseline) { "ROLLED_BACK" } else { "NEEDS_RECOVERY" }
    Write-R2Json -Path $txRecord -Value $record
    Write-R2Log "rolled back to $final (exit 4)" warn $log
    Exit-With 4
}

$record.state = "COMMITTED"
$record | Add-Member -NotePropertyName finished_at -NotePropertyValue ((Get-Date).ToString("o"))
$record | Add-Member -NotePropertyName installed_sha256 -NotePropertyValue $after
Write-R2Json -Path $txRecord -Value $record
Write-R2Log "installed: $after  ($((Get-Item -LiteralPath $target).Length.ToString('N0')) B)" ok $log

# ── 9. unpacked tree (identical content, idempotent sync) ────────────────────
$srcUnpacked = Join-Path $r2 "build\pkg\app.asar.unpacked"
$dstUnpacked = Join-Path $resourcesDir "app.asar.unpacked"
if ((Test-Path -LiteralPath $srcUnpacked) -and -not (Test-Path -LiteralPath $dstUnpacked)) {
    Write-R2Log "note: target has no app.asar.unpacked; the patched archive does not need one" warn $log
}
Write-R2Log "install OK" ok $log
Write-R2Log "next: start DeepSeek Harness" ok $log
Exit-With 0

