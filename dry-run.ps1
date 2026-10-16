<#
.SYNOPSIS
    Report exactly what install.ps1 would do, without changing anything.

.DESCRIPTION
    Validates the whole install path so failures surface while the assistant
    session is still alive: target and patched archive exist and differ, the
    processes holding the archive are named, the backup name is free, and the
    destination is writable.

.PARAMETER InstallDir
    The DeepSeek Harness installation directory.

.PARAMETER Patched
    The patched archive to install.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "E:\Software\DeepSeek Harness",
    [string]$Patched
)

$ErrorActionPreference = "Continue"
$problems = 0

# $PSScriptRoot is not populated while default parameter values are bound, so the
# script directory is resolved here instead. Without this, running the script via
# `powershell -File` fails with "Cannot bind argument to parameter 'Path'" the
# moment a default value joins a path.
$scriptDir = if ($PSScriptRoot) {
    $PSScriptRoot
} elseif ($MyInvocation.MyCommand.Path) {
    Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    (Get-Location).Path
}
if (-not $Patched) { $Patched = Join-Path $scriptDir "work\app.asar.patched" }

function Check($ok, $label, $detail) {
    if ($ok) {
        Write-Host ("[ok]   {0}" -f $label) -ForegroundColor Green
    } else {
        Write-Host ("[FAIL] {0}" -f $label) -ForegroundColor Red
        $script:problems++
    }
    if ($detail) { Write-Host ("       {0}" -f $detail) }
}

Write-Host "=== install.ps1 dry run ===" -ForegroundColor Cyan
Write-Host ""

# 1. script itself
$self = Join-Path $PSScriptRoot "install.ps1"
Check (Test-Path -LiteralPath $self) "install.ps1 present" $self

$tokens = $null; $errors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile($self, [ref]$tokens, [ref]$errors)
Check ($errors.Count -eq 0) "install.ps1 parses" ($errors | ForEach-Object { $_.Message }) -join '; '

# 2. target
$target = Join-Path $InstallDir "resources\app.asar"
Check (Test-Path -LiteralPath $target) "target app.asar present" $target
if (Test-Path -LiteralPath $target) {
    $info = Get-Item -LiteralPath $target
    Check ($info.Length -gt 100MB) "target looks like a real archive" ("{0:N0} bytes" -f $info.Length)
}

# 3. patched input
Check (Test-Path -LiteralPath $Patched) "patched archive present" $Patched
if (Test-Path -LiteralPath $Patched) {
    $p = Get-Item -LiteralPath $Patched
    Write-Host ("       {0:N0} bytes" -f $p.Length)
    if (Test-Path -LiteralPath $target) {
        $same = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -eq
                (Get-FileHash -LiteralPath $Patched -Algorithm SHA256).Hash
        Check (-not $same) "patched archive differs from installed one" `
            $(if ($same) { "identical - patch was already applied, or --out reused" } else { "differs, as expected" })
    }
}

# 4. lock status and holders
$running = Get-Process -Name "DeepSeek Harness" -ErrorAction SilentlyContinue
if ($running) {
    Write-Host ("[info] DeepSeek Harness running: PID {0}" -f ($running.Id -join ', ')) -ForegroundColor Yellow
} else {
    Write-Host "[ok]   DeepSeek Harness not running (archive is replaceable now)" -ForegroundColor Green
}
if (Test-Path -LiteralPath $target) {
    try {
        $h = [System.IO.File]::Open($target, "Open", "ReadWrite", "None"); $h.Close()
        Write-Host "[ok]   target is writable (no lock held)" -ForegroundColor Green
    } catch {
        Write-Host ("[info] target is locked right now: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
        Write-Host "       -> install.cmd kills the app and waits for the lock to clear."
    }
}

# 5. destination writability
$dir = Split-Path -Parent $target
$probe = Join-Path $dir "._write_probe"
try {
    Set-Content -LiteralPath $probe -Value "probe" -ErrorAction Stop
    Remove-Item -LiteralPath $probe -Force
    Check $true "install directory is writable" $dir
} catch {
    Check $false "install directory is writable" $_.Exception.Message
}

# 6. backup name free + newest existing backup
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = "$target.original-$stamp"
Check (-not (Test-Path -LiteralPath $backup)) "backup name is free" $backup
$existing = Get-ChildItem -LiteralPath $dir -Filter "app.asar.original-*" -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host ("[info] existing backups: {0}" -f (($existing | Sort-Object LastWriteTime -Descending |
        Select-Object -First 3 | ForEach-Object { $_.Name }) -join ', '))
}

# 7. companion scripts
foreach ($f in @("rollback.ps1", "install.cmd", "rollback.cmd", "verify-asar.py", "patch-asar.py")) {
    Check (Test-Path -LiteralPath (Join-Path $PSScriptRoot $f)) "$f present" (Join-Path $PSScriptRoot $f)
}

# 8. python available for the rebuild path
$py = Get-Command python -ErrorAction SilentlyContinue
Check ($null -ne $py) "python on PATH (only needed to rebuild)" $(if ($py) { $py.Source } else { "not found - rebuild steps will not work, install still will" })

Write-Host ""
if ($problems -eq 0) {
    Write-Host "All checks passed. install.cmd is ready to run." -ForegroundColor Green
} else {
    Write-Host ("{0} check(s) failed - see the [FAIL] lines above." -f $problems) -ForegroundColor Red
}

