<#
.SYNOPSIS
    Roll back the R2 patched DSH Desktop shell (B-06).

.DESCRIPTION
    Restores <AppDir>\resources\app.asar from the backup recorded in a transaction
    that belongs to exactly that AppDir. Unlike the installer, rollback does not
    need an authorisation file - it needs an unambiguous transaction.

    * A rollback is bound to the transaction's own backup file; the "newest
      app.asar.original-*" heuristic is never used.
    * With several candidate transactions the newest COMMITTED one for this
      AppDir wins; a PREPARED transaction that never finished is handled by
      restoring from its own bound backup.
    * No transaction for this AppDir, or a TxId that belongs to another AppDir,
      is refused with exit 8 and the file is left alone.
    * No process is ever terminated; it waits for the app and Host to exit.

.PARAMETER AppDir
    Installation directory to roll back.

.PARAMETER TxId
    Specific transaction to apply. When omitted, the newest suitable one for this
    AppDir is chosen.

.PARAMETER WhatIf
    Report the plan without changing anything.
#>
[CmdletBinding()]
param(
    [string]$AppDir = "E:\Software\DeepSeek Harness",
    [string]$Manifest,
    [string]$TxId,
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

$evidence = Join-Path $r2 "evidence"
$txDir = Join-Path $r2 "tx"
New-Item -ItemType Directory -Force $evidence, $txDir | Out-Null
$log = Join-Path $evidence ("B-06-rollback-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")

. (Join-Path $kit "log.ps1")

function Exit-With([int]$code) { exit $code }

Write-R2Log "rollback: start" info $log
$appDirFull = [System.IO.Path]::GetFullPath($AppDir).TrimEnd("\")
Write-R2Log "app dir  : $appDirFull" info $log

# ── manifest (baseline + patched) ────────────────────────────────────────────
try { $mf = Test-R2Manifest -Path $Manifest } catch { Write-R2Log $_ err $log; Exit-With 8 }
$baseline = "$($mf.baseline_sha256)".ToLower()
$patched = "$($mf.patched_sha256)".ToLower()

$target = Join-Path $AppDir "resources\app.asar"
if (-not (Test-Path -LiteralPath $target)) { Write-R2Log "target not found: $target (exit 8)" err $log; Exit-With 8 }
$current = (Get-R2Sha256 -Path $target).ToLower()
Write-R2Log "current  : $current" info $log
if ($current -eq $baseline) { Write-R2Log "already the pristine build - nothing to do" ok $log; Exit-With 0 }

# ── ancestor guard ───────────────────────────────────────────────────────────
$inside = @(Test-R2InsideDir -Directory $AppDir)
if ($inside.Count -gt 0) {
    Write-R2Log "started from inside the target directory - refuse (exit 2)" err $log
    foreach ($proc in $inside) { Write-R2Log ("  ancestor pid {0} {1}" -f $proc.ProcessId, $proc.ExecutablePath) info $log }
    Exit-With 2
}

# ── pick the transaction ─────────────────────────────────────────────────────
# Each entry is a wrapper object. `$list += ($path, $json)` would FLATTEN the
# pair into the array, so `$_[1]` would index a string and app_dir would be null
# (that produced "The path is not of a legal form" from GetFullPath).
$records = @()
foreach ($file in Get-ChildItem -LiteralPath $txDir -Filter "install-*.json" -ErrorAction SilentlyContinue) {
    try {
        $parsed = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $records += [pscustomobject]@{ Path = $file.FullName; Rec = $parsed }
    } catch { }
}
$mine = @($records | Where-Object {
    $dir = "$($_.Rec.app_dir)"
    if (-not $dir) { return $false }
    ([System.IO.Path]::GetFullPath($dir).TrimEnd("\")) -ieq $appDirFull
})

if ($TxId) {
    $mine = @($mine | Where-Object { "$($_.Rec.txid)" -eq $TxId })
    if ($mine.Count -eq 0) {
        Write-R2Log "no transaction $TxId belongs to $appDirFull (exit 8)" err $log
        Exit-With 8
    }
}
if ($mine.Count -eq 0) {
    Write-R2Log "no install transaction recorded for $appDirFull (exit 8)" err $log
    Write-R2Log "refusing: the newest app.asar.original-* is NOT used as a guess" warn $log
    Exit-With 8
}
if ($mine.Count -gt 1) {
    $committed = @($mine | Where-Object { "$($_.Rec.state)" -eq "COMMITTED" })
    if ($committed.Count -ge 1) { $mine = @($committed | Sort-Object { $_.Rec.started_at } | Select-Object -Last 1) }
    else { $mine = @($mine | Sort-Object { $_.Rec.started_at } | Select-Object -Last 1) }
}
$chosen = $mine[0].Rec
$chosenPath = $mine[0].Path
Write-R2Log "transaction: $chosenPath  state=$($chosen.state)" ok $log

# ── the backup must exist and be the baseline ────────────────────────────────
$candidates = @($chosen.backup_r2, $chosen.backup_in_place) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
if ($candidates.Count -eq 0) { Write-R2Log "transaction backup missing (exit 8)" err $log; Exit-With 8 }
$source = $null
foreach ($candidate in $candidates) {
    if ((Get-R2Sha256 -Path $candidate).ToLower() -eq $baseline) { $source = $candidate; break }
}
if (-not $source) {
    Write-R2Log "no bound backup matches BASELINE (exit 8)" err $log
    Exit-With 8
}
Write-R2Log "restore source: $source" ok $log

if ($WhatIf) {
    Write-R2Log "WhatIf: would wait for exit, stage, then File.Replace with $source" warn $log
    Exit-With 0
}

# ── wait, then swap ──────────────────────────────────────────────────────────
$hostNames = @()
if ($mf.host_process_names) { $hostNames = @($mf.host_process_names) }
if (-not (Wait-R2Exited -Directory $AppDir -TimeoutSeconds 120 -ExtraNames $hostNames -LogPath $log)) {
    Write-R2Log "app or Host still running (exit 5)" err $log
    Exit-With 5
}
Write-R2Log "app stopped" ok $log

$resourcesDir = Split-Path -Parent $target
$restore = Join-Path $resourcesDir ("app.asar.r2-rollback-" + (New-R2TxId))
Copy-Item -LiteralPath $source -Destination $restore -Force
if ((Get-R2Sha256 -Path $restore).ToLower() -ne $baseline) {
    Write-R2Log "staging hash mismatch (exit 8)" err $log
    Remove-Item -LiteralPath $restore -Force -ErrorAction SilentlyContinue
    Exit-With 8
}
try {
    Replace-R2File -Source $restore -Destination $target
} catch {
    Write-R2Log "replace failed: $_" err $log
    Remove-Item -LiteralPath $restore -Force -ErrorAction SilentlyContinue
    Exit-With 6
}
$after = (Get-R2Sha256 -Path $target).ToLower()
if ($after -ne $baseline) { Write-R2Log "verify failed after replace (exit 6)" err $log; Exit-With 6 }

$rollbackRecord = [ordered]@{
    txid             = (New-R2TxId)
    tool             = "rollback"
    started_at       = (Get-Date).ToString("o")
    app_dir          = $appDirFull
    source_tx        = $chosen.txid
    source_tx_file   = $chosenPath
    restored_sha256  = $after
    before_sha256    = $current
    state            = "ROLLED_BACK"
}
Write-R2Json -Path (Join-Path $txDir ("rollback-$($rollbackRecord.txid).json")) -Value $rollbackRecord
Write-R2Log "restored: $after  ($((Get-Item -LiteralPath $target).Length.ToString('N0')) B)" ok $log
Write-R2Log "rollback OK" ok $log
Exit-With 0

