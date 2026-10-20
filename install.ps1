# One-command install of the "Open in new window" feature for DSH Desktop.
#
#   irm https://raw.githubusercontent.com/CHIANGANGSTER/dsh-session-window/main/install.ps1 | iex
#
# What it does, in order:
#   1. finds the DSH Desktop installation and the profile
#   2. refuses unless the installed app.asar is the supported pristine build
#   3. downloads the patch definition (diffs only, a few KB)
#   4. stops DSH, rebuilds the archive locally, verifies it byte-for-byte
#   5. renames the original aside and puts the rebuilt archive in place
#   6. registers the client plugin as a profile dependency
#   7. starts DSH again
#
# Nothing is downloaded prebuilt: the archive is rebuilt from diffs on your own
# machine, and its SHA-256 must match the published value before it is installed.
# Undo with uninstall.ps1.
#
# Notes
#   * Run it in Windows Terminal or PowerShell, not from inside a DSH session:
#     the app has to be closed while its archive is replaced.
#   * Set DSH_APP_DIR to override detection:
#       $env:DSH_APP_DIR = 'D:\DeepSeek Harness'; irm ... | iex
#   * ASCII-only on purpose: PowerShell 5.1 decodes a BOM-less UTF-8 file as the
#     system ANSI code page.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$BaselineSha = '47874618bf5b3011fcaac10cd4c85f69da333e70d4f99b921207c78d0999512a'
$PatchedSha  = '40b471241d607c5b1c04f555b6b68d63e387df5a1b694fa2f2147625d5986229'
$RepoRaw     = 'https://raw.githubusercontent.com/CHIANGANGSTER/dsh-session-window/main'
$TgzUrl      = 'https://github.com/CHIANGANGSTER/dsh-session-window/releases/latest/download/dsh-session-window-client.tgz'
$PluginName  = 'dsh-session-window-client'

function Say([string]$Text, [string]$Level = 'info') {
    $prefix = switch ($Level) { 'ok' { '  ok  ' } 'warn' { ' warn ' } 'err' { ' fail ' } 'step' { '  ->  ' } default { '      ' } }
    $colour = switch ($Level) { 'ok' { 'Green' } 'warn' { 'Yellow' } 'err' { 'Red' } 'step' { 'Cyan' } default { 'Gray' } }
    Write-Host "$prefix$Text" -ForegroundColor $colour
}
function Get-Sha256([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower() }

Write-Host ''
Write-Host '  DSH Desktop - open a Session in a second window' -ForegroundColor White
Write-Host '  ----------------------------------------------' -ForegroundColor DarkGray
Write-Host ''

# ── 1. locate the app ────────────────────────────────────────────────────────
Say 'locating DeepSeek Harness' step
$appDir = $env:DSH_APP_DIR
if (-not $appDir) {
    $running = Get-CimInstance Win32_Process -Filter "Name = 'DeepSeek Harness.exe'" -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($running -and $running.ExecutablePath) { $appDir = Split-Path -Parent $running.ExecutablePath }
}
if (-not $appDir) {
    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DeepSeek Harness'),
        (Join-Path $env:LOCALAPPDATA 'DeepSeek Harness'),
        'C:\Program Files\DeepSeek Harness',
        'C:\Program Files (x86)\DeepSeek Harness'
    )
    foreach ($root in $roots) {
        if (Test-Path -LiteralPath (Join-Path $root 'resources\app.asar')) { $appDir = $root; break }
    }
}
if (-not $appDir) {
    foreach ($key in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*', 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*')) {
        $hit = Get-ItemProperty $key -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like '*DeepSeek*Harness*' -and $_.InstallLocation } |
            Select-Object -First 1
        if ($hit) { $appDir = $hit.InstallLocation.TrimEnd('\'); break }
    }
}
$asar = if ($appDir) { Join-Path $appDir 'resources\app.asar' } else { $null }
if (-not $asar -or -not (Test-Path -LiteralPath $asar)) {
    Say 'could not find DeepSeek Harness. Set $env:DSH_APP_DIR and run again.' err
    return
}
$exe = Join-Path $appDir 'DeepSeek Harness.exe'
Say "app      $appDir" ok

$profileDir = Join-Path $env:USERPROFILE '.dsh\profiles\desktop'
if ($env:DSH_HOME) { $profileDir = Join-Path $env:DSH_HOME 'profiles\desktop' }
Say "profile  $profileDir" ok

# ── 2. what is installed right now ───────────────────────────────────────────
$currentSha = Get-Sha256 $asar
Say "app.asar $currentSha"
$needsPatch = $true
if ($currentSha -eq $PatchedSha) {
    Say 'the shell is already patched; skipping that step' ok
    $needsPatch = $false
} elseif ($currentSha -ne $BaselineSha) {
    Say 'this build of DeepSeek Harness is not supported by this patch yet.' err
    Say "  expected (pristine) $BaselineSha" 
    Say "  found               $currentSha"
    Say '  open an issue with that hash and the version from the About dialog.'
    return
}

if ($env:DSH_INSTALL_CHECK -eq '1') {
    Say 'check mode: detection and hashes look right, nothing was changed' ok
    return
}

$temp = Join-Path $env:TEMP ('dsh-session-window-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $temp | Out-Null
Say "workdir  $temp" ok

# ── 3. fetch the patch definition ────────────────────────────────────────────
Say 'downloading the patch definition' step
Invoke-WebRequest -Uri "$RepoRaw/patch-asar.mjs" -OutFile (Join-Path $temp 'patch-asar.mjs') -UseBasicParsing
$specDir = Join-Path $temp 'patches'
New-Item -ItemType Directory -Force -Path $specDir | Out-Null
foreach ($name in @('main.js.json', 'preload-app.cjs.json')) {
    Invoke-WebRequest -Uri "$RepoRaw/patches/r2/$name" -OutFile (Join-Path $specDir $name) -UseBasicParsing
}
Say 'patch definition ready' ok

# ── 4. stop DSH ──────────────────────────────────────────────────────────────
$root = [System.IO.Path]::GetFullPath($appDir).TrimEnd('\')
function Get-AppProcesses {
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ExecutablePath -and
        ([System.IO.Path]::GetFullPath($_.ExecutablePath)).StartsWith("$root\", [System.StringComparison]::OrdinalIgnoreCase)
    })
}
$procs = if ($needsPatch) { Get-AppProcesses } else { @() }
if ($procs.Count -gt 0) {
    Say "closing DeepSeek Harness ($($procs.Count) process(es))" step
    foreach ($proc in $procs) {
        try { Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop } catch { }
    }
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-AppProcesses).Count -gt 0 -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 400 }
    if ((Get-AppProcesses).Count -gt 0) { Say 'the app did not exit; close it and run again' err; return }
    Say 'app closed' ok
} elseif ($needsPatch) {
    Say 'app was not running' ok
} else {
    Say 'shell already patched; leaving the running app alone' ok
}

# ── 5. rebuild and verify ────────────────────────────────────────────────────
if ($needsPatch) {
    Say 'rebuilding the shell archive (this takes a few seconds)' step
    $out = Join-Path $temp 'app.asar'
    $env:ELECTRON_RUN_AS_NODE = '1'
    try {
        & $exe (Join-Path $temp 'patch-asar.mjs') --asar $asar --spec $specDir --out $out --expect-sha256 $BaselineSha
        if ($LASTEXITCODE -ne 0) { Say 'the patcher refused to build (see the message above)' err; return }
    } finally {
        Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
    }
    $builtSha = Get-Sha256 $out
    if ($builtSha -ne $PatchedSha) {
        Say 'the rebuilt archive does not match the published hash' err
        Say "  built    $builtSha"
        Say "  expected $PatchedSha"
        return
    }
    Say 'rebuilt archive verified' ok

    # ── 6. swap it in ────────────────────────────────────────────────────────
    $resources = Join-Path $appDir 'resources'
    $backup = Join-Path $resources ('app.asar.before-session-window-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    Copy-Item -LiteralPath $asar -Destination $backup -Force
    if ((Get-Sha256 $backup) -ne $BaselineSha) { Say 'backup did not verify; nothing was replaced' err; return }
    Say "backup   $backup" ok

    $staging = Join-Path $resources 'app.asar.incoming'
    Copy-Item -LiteralPath $out -Destination $staging -Force
    [System.IO.File]::Replace($staging, $asar, $null, $true)
    if ((Get-Sha256 $asar) -ne $PatchedSha) {
        Say 'the swap did not land as expected; restoring the backup' err
        Copy-Item -LiteralPath $backup -Destination $asar -Force
        return
    }
    Say 'shell patched' ok
}

# ── 7. register the plugin as a profile dependency ───────────────────────────
$pnpm = Join-Path $appDir 'resources\runtime\primary-runtime\dependencies\pnpm\bin\pnpm.mjs'
if (-not (Test-Path -LiteralPath $pnpm)) {
    Say 'the plugin was not installed automatically (pnpm not found in the app bundle).' warn
    Say '  install it from the Plugins page with this address:' warn
    Say "  $TgzUrl"
} elseif (-not (Test-Path -LiteralPath (Join-Path $profileDir 'package.json'))) {
    Say "profile not found at $profileDir; skipping the plugin" warn
} else {
    Say 'installing the client plugin' step
    $localPkgs = Join-Path $profileDir 'local-pkgs'
    New-Item -ItemType Directory -Force -Path $localPkgs | Out-Null
    $tgz = Join-Path $localPkgs "$PluginName.tgz"
    Invoke-WebRequest -Uri $TgzUrl -OutFile $tgz -UseBasicParsing

    $env:ELECTRON_RUN_AS_NODE = '1'
    try {
        Push-Location $profileDir
        & $exe $pnpm add "file:local-pkgs/$PluginName.tgz" --prefer-offline | Out-Null
        $addCode = $LASTEXITCODE
        Pop-Location
    } finally {
        Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
    }
    if ($addCode -ne 0) {
        Say 'pnpm could not add the plugin; install it from the Plugins page with the address above' warn
    } else {
        # list it in dsh.profile.bundles so the Host actually loads it
        $pkgPath = Join-Path $profileDir 'package.json'
        $text = [System.IO.File]::ReadAllText($pkgPath)
        if ($text -notmatch [regex]::Escape('"' + $PluginName + '"')) {
            $marker = '"bundles": ['
            $index = $text.IndexOf($marker)
            if ($index -ge 0) {
                $insertAt = $index + $marker.Length
                $text = $text.Insert($insertAt, "`r`n        `"$PluginName`",")
                [System.IO.File]::WriteAllText($pkgPath, $text, (New-Object System.Text.UTF8Encoding($false)))
                Say 'registered in dsh.profile.bundles' ok
            } else {
                Say 'could not edit dsh.profile.bundles automatically' warn
                Say '  add it from the Plugins page instead' warn
            }
        } else {
            Say 'already listed in dsh.profile.bundles' ok
        }
        Say 'plugin installed' ok
    }
}

# ── 8. start DSH ─────────────────────────────────────────────────────────────
Say 'starting DeepSeek Harness' step
Start-Process -FilePath $exe | Out-Null
Start-Sleep -Seconds 3
Say 'done. Right-click any Session in the sidebar.' ok
Say "backup of the original archive: $(Join-Path (Join-Path $appDir 'resources') 'app.asar.before-session-window-*')"
Say 'undo with uninstall.ps1'
