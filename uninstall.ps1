# Undo the "Open in new window" install for DSH Desktop.
#
#   irm https://raw.githubusercontent.com/CHIANGANGSTER/dsh-session-window/main/uninstall.ps1 | iex
#
# Puts the original app.asar back, removes the client plugin from the profile,
# and starts DSH again. Only the two things install.ps1 added are touched; other
# plugins, sessions and settings are left alone.
#
# ASCII-only on purpose (PowerShell 5.1 reads a BOM-less UTF-8 file as ANSI).

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$BaselineSha = '47874618bf5b3011fcaac10cd4c85f69da333e70d4f99b921207c78d0999512a'
$PatchedSha  = '40b471241d607c5b1c04f555b6b68d63e387df5a1b694fa2f2147625d5986229'
$PluginName  = 'dsh-session-window-client'

function Say([string]$Text, [string]$Level = 'info') {
    $prefix = switch ($Level) { 'ok' { '  ok  ' } 'warn' { ' warn ' } 'err' { ' fail ' } 'step' { '  ->  ' } default { '      ' } }
    $colour = switch ($Level) { 'ok' { 'Green' } 'warn' { 'Yellow' } 'err' { 'Red' } 'step' { 'Cyan' } default { 'Gray' } }
    Write-Host "$prefix$Text" -ForegroundColor $colour
}
function Get-Sha256([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower() }

Write-Host ''
Write-Host '  DSH Desktop - remove the second-window feature' -ForegroundColor White
Write-Host '  ---------------------------------------------' -ForegroundColor DarkGray
Write-Host ''

$appDir = $env:DSH_APP_DIR
if (-not $appDir) {
    $running = Get-CimInstance Win32_Process -Filter "Name = 'DeepSeek Harness.exe'" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($running -and $running.ExecutablePath) { $appDir = Split-Path -Parent $running.ExecutablePath }
}
if (-not $appDir) {
    foreach ($root in @((Join-Path $env:LOCALAPPDATA 'Programs\DeepSeek Harness'), 'C:\Program Files\DeepSeek Harness')) {
        if (Test-Path -LiteralPath (Join-Path $root 'resources\app.asar')) { $appDir = $root; break }
    }
}
if (-not $appDir) { Say 'could not find DeepSeek Harness. Set $env:DSH_APP_DIR and run again.' err; return }
$asar = Join-Path $appDir 'resources\app.asar'
$exe = Join-Path $appDir 'DeepSeek Harness.exe'
Say "app      $appDir" ok

$profileDir = Join-Path $env:USERPROFILE '.dsh\profiles\desktop'
if ($env:DSH_HOME) { $profileDir = Join-Path $env:DSH_HOME 'profiles\desktop' }

$root = [System.IO.Path]::GetFullPath($appDir).TrimEnd('\')
function Get-AppProcesses {
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ExecutablePath -and ([System.IO.Path]::GetFullPath($_.ExecutablePath)).StartsWith("$root\", [System.StringComparison]::OrdinalIgnoreCase)
    })
}

$procs = Get-AppProcesses
if ($procs.Count -gt 0) {
    Say 'closing DeepSeek Harness' step
    foreach ($proc in $procs) { try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop } catch { } }
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-AppProcesses).Count -gt 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 400 }
    if ((Get-AppProcesses).Count -gt 0) { Say 'the app did not exit; close it and run again' err; return }
}

# ── restore the original archive ─────────────────────────────────────────────
$current = Get-Sha256 $asar
if ($current -eq $BaselineSha) {
    Say 'the shell is already the original build' ok
} elseif ($current -ne $PatchedSha) {
    Say "app.asar is neither the original nor the patched build ($current); not touching it" err
} else {
    $backups = @(Get-ChildItem -LiteralPath (Join-Path $appDir 'resources') -Filter 'app.asar.before-session-window-*' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending)
    $restored = $false
    foreach ($backup in $backups) {
        if ((Get-Sha256 $backup.FullName) -ne $BaselineSha) { continue }
        $staging = Join-Path (Join-Path $appDir 'resources') 'app.asar.restoring'
        Copy-Item -LiteralPath $backup.FullName -Destination $staging -Force
        [System.IO.File]::Replace($staging, $asar, $null, $true)
        if ((Get-Sha256 $asar) -eq $BaselineSha) { Say "restored from $($backup.Name)" ok; $restored = $true; break }
    }
    if (-not $restored) { Say 'no verified backup found; the original build cannot be restored automatically' err }
}

# ── remove the plugin ────────────────────────────────────────────────────────
$pkgPath = Join-Path $profileDir 'package.json'
if (Test-Path -LiteralPath $pkgPath) {
    $pnpm = Join-Path $appDir 'resources\runtime\primary-runtime\dependencies\pnpm\bin\pnpm.mjs'
    if (Test-Path -LiteralPath $pnpm) {
        $env:ELECTRON_RUN_AS_NODE = '1'
        try {
            Push-Location $profileDir
            & $exe $pnpm remove $PluginName 2>&1 | Out-Null
            Pop-Location
        } finally {
            Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
        }
    }
    $text = [System.IO.File]::ReadAllText($pkgPath)
    $needle = '"' + $PluginName + '"'
    if ($text -match [regex]::Escape($needle)) {
        $text = [regex]::Replace($text, '\s*' + [regex]::Escape($needle) + ',?', '')
        [System.IO.File]::WriteAllText($pkgPath, $text, (New-Object System.Text.UTF8Encoding($false)))
        Say 'removed from dsh.profile.bundles' ok
    }
    $tgz = Join-Path (Join-Path $profileDir 'local-pkgs') "$PluginName.tgz"
    if (Test-Path -LiteralPath $tgz) { Remove-Item -LiteralPath $tgz -Force; Say 'removed the plugin package' ok }
} else {
    Say "no profile at $profileDir; skipped the plugin" warn
}

Say 'starting DeepSeek Harness' step
Start-Process -FilePath $exe | Out-Null
Say 'done' ok
