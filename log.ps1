<#
.SYNOPSIS
    Shared logging and app-control helpers for the DSH session-window scripts.

.DESCRIPTION
    ASCII-only on purpose: PowerShell 5.1 decodes a BOM-less UTF-8 script as the
    system ANSI code page (GBK on a Chinese Windows), which corrupted Chinese
    literals and swallowed their closing quotes. The Chinese narrative lives in
    README.md, which is never executed.

    Log lines are appended with System.IO.File rather than Add-Content, so a
    -WhatIf switch on the caller cannot silently suppress the log.

    Dot-source it:   . "$scriptDir\log.ps1" -LogPath $path
#>
[CmdletBinding()]
param(
    [string]$LogPath,
    [switch]$Quiet
)

$script:SessionLogPath = $LogPath
$script:SessionLogQuiet = [bool]$Quiet

if ($script:SessionLogPath) {
    try {
        $dir = Split-Path -Parent $script:SessionLogPath
        if ($dir -and -not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
        "=== DSH session-window log $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" |
            Set-Content -LiteralPath $script:SessionLogPath -Encoding ASCII -ErrorAction Stop
    } catch {
        $script:SessionLogPath = $null
        Write-Warning "could not open the log file: $($_.Exception.Message)"
    }
}

function Write-SessionLog {
    <#
    .SYNOPSIS
        Append one line to the console and to the log file.
    .PARAMETER Message
        Text to record. Keep it ASCII so no code page can corrupt it.
    .PARAMETER Level
        info, ok, warn or error.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, Position = 0)][string]$Message,
        [ValidateSet("info", "ok", "warn", "error")][string]$Level = "info"
    )

    $prefix = switch ($Level) {
        "ok" { "[ok]   " }
        "warn" { "[warn] " }
        "error" { "[FAIL] " }
        default { "       " }
    }

    if (-not $script:SessionLogQuiet) {
        $colour = switch ($Level) {
            "ok" { "Green" }
            "warn" { "Yellow" }
            "error" { "Red" }
            default { "Gray" }
        }
        Write-Host "$prefix$Message" -ForegroundColor $colour
    }

    if ($script:SessionLogPath) {
        $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        try {
            $utf8 = New-Object System.Text.ASCIIEncoding
            $bytes = $utf8.GetBytes("$stamp $prefix$Message`r`n")
            $stream = [System.IO.File]::Open($script:SessionLogPath, "Append", "Write", "Read")
            try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
        } catch {
            # logging must never take the install down
        }
    }
}

function Stop-AppProcesses {
    <#
    .SYNOPSIS
        Stop DeepSeek Harness without touching the caller.
    .PARAMETER Force
        Stop the processes; otherwise only report what is running.
    .PARAMETER DryRun
        Report only, stop nothing.
    .OUTPUTS
        $true when no app process remains.
    #>
    [CmdletBinding()]
    param(
        [switch]$Force,
        [switch]$DryRun
    )

    $running = Get-Process -Name "DeepSeek Harness" -ErrorAction SilentlyContinue
    if (-not $running) {
        Write-SessionLog "app running : no" -Level ok
        return $true
    }
    Write-SessionLog ("app running : PID {0}" -f ($running.Id -join ", ")) -Level warn
    if ($DryRun) {
        Write-SessionLog "dry run     : would stop the app's own processes" -Level warn
        Write-SessionLog "dry run     : NOTE the app still holds the file lock after this" -Level warn
        return $false
    }
    if (-not $Force) {
        Write-SessionLog "pass -Force to stop it (or close the app yourself)" -Level error
        return $false
    }
    Write-SessionLog "stopping    : only the app's own processes (never taskkill /T)" -Level warn
    $running | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    $left = Get-Process -Name "DeepSeek Harness" -ErrorAction SilentlyContinue
    if ($left) {
        Write-SessionLog ("still alive : {0}" -f ($left.Id -join ", ")) -Level error
        return $false
    }
    Write-SessionLog "stopped     : no app process remains" -Level ok
    return $true
}

function Wait-ArchiveWritable {
    <#
    .SYNOPSIS
        Wait for a file to become exclusively writable.
    .PARAMETER Path
        The file the app had open.
    .PARAMETER Seconds
        How long to wait before giving up.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [int]$Seconds = 45
    )

    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $handle = [System.IO.File]::Open($Path, "Open", "ReadWrite", "None")
            $handle.Close()
            Write-SessionLog "lock        : released" -Level ok
            return $true
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    $holders = (Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "DeepSeek|node|node_repl" } |
        Select-Object -ExpandProperty Id) -join ", "
    Write-SessionLog ("lock        : still held after {0}s (candidates: {1})" -f $Seconds, $holders) -Level error
    return $false
}

# =============================================================================
#  R2 helpers (appended by B-06). Kept in log.ps1 so there is one shared library.
#  ASCII-only on purpose: PowerShell 5.1 decodes a BOM-less UTF-8 script as the
#  system ANSI code page, which corrupts non-ASCII literals.
# =============================================================================

function Write-R2Json {
    <#
        Write JSON as UTF-8 WITHOUT a BOM.

        PowerShell 5.1's `Set-Content -Encoding UTF8` emits a BOM, and the DSH Host
        parses a profile manifest with plain JSON.parse, which rejects a leading
        U+FEFF. That caused:
            DesktopHostFatalError: Unexpected token '', "{ "name"... is not valid JSON
              at readProfileManifest
        Every JSON file this kit writes goes through here.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)]$Value,
        [int]$Depth = 8
    )
    $json = $Value | ConvertTo-Json -Depth $Depth
    [System.IO.File]::WriteAllText($Path, $json, (New-Object System.Text.UTF8Encoding($false)))
}
function Get-R2Sha256 {
    <#
        SHA-256 of a file, upper-case hex like Get-FileHash.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}
function New-R2TxId {
    [CmdletBinding()]
    param()
    "{0}-{1}" -f (Get-Date -Format "yyyyMMddHHmmss"), (Get-Random -Minimum 1000 -Maximum 9999)
}

function Write-R2Log {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Message,
        [ValidateSet("info", "ok", "warn", "err")][string]$Level = "info",
        [string]$Path
    )
    $prefix = switch ($Level) { "ok" { "[ok]   " } "warn" { "[warn] " } "err" { "[FAIL] " } default { "       " } }
    $colour = switch ($Level) { "ok" { "Green" } "warn" { "Yellow" } "err" { "Red" } default { "Gray" } }
    Write-Host "$prefix$Message" -ForegroundColor $colour
    if ($Path) {
        try {
            if (-not (Test-Path -LiteralPath $Path)) {
                [System.IO.File]::WriteAllText($Path, "", (New-Object System.Text.UTF8Encoding($true)))
            }
            [System.IO.File]::AppendAllText($Path, "$prefix$Message`r`n", (New-Object System.Text.UTF8Encoding($false)))
        } catch { }
    }
}

function Get-R2Ancestors {
    [CmdletBinding()]
    param()
    $chain = @()
    $current = $PID
    for ($i = 0; $i -lt 12 -and $current) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$current" -ErrorAction SilentlyContinue
        if (-not $proc) { break }
        $chain += $proc
        if ($proc.ProcessId -eq $proc.ParentProcessId) { break }
        $current = $proc.ParentProcessId
    }
    return $chain
}

function Test-R2InsideDir {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Directory,
        [object[]]$Chain
    )
    if (-not $Chain) { $Chain = @(Get-R2Ancestors) }
    $root = [System.IO.Path]::GetFullPath($Directory).TrimEnd("\")
    $hits = @()
    foreach ($proc in $Chain) {
        $exe = $proc.ExecutablePath
        if (-not $exe) { continue }
        $full = [System.IO.Path]::GetFullPath($exe)
        if ($full.StartsWith("$root\", [System.StringComparison]::OrdinalIgnoreCase)) { $hits += $proc }
    }
    return $hits
}

function Wait-R2Exited {
    <#
        Wait until no process whose executable lives under $Directory is running.
        Never terminates anything. Returns $true when clear, $false on timeout.
        $ExtraNames lets the caller add the Host process signature from A-09.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Directory,
        [int]$TimeoutSeconds = 120,
        [string[]]$ExtraNames = @(),
        [string]$LogPath,
        [object[]]$Chain
    )
    if (-not $Chain) { $Chain = @(Get-R2Ancestors) }
    $selfIds = @($Chain | Select-Object -ExpandProperty ProcessId)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $blocking = @()
    while ((Get-Date) -lt $deadline) {
        $blocking = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            if ($selfIds -contains $_.ProcessId) { return $false }
            if ($ExtraNames -contains $_.Name) { return $true }
            $exe = $_.ExecutablePath
            if (-not $exe) { return $false }
            ([System.IO.Path]::GetFullPath($exe)).StartsWith(
                [System.IO.Path]::GetFullPath($Directory), [System.StringComparison]::OrdinalIgnoreCase)
        })
        if (-not $blocking) { return $true }
        Start-Sleep -Milliseconds 700
    }
    if ($LogPath) {
        foreach ($proc in $blocking) { Write-R2Log ("still running: pid {0} {1}" -f $proc.ProcessId, $proc.Name) warn $LogPath }
    }
    return $false
}

function Replace-R2File {
    <#
        Atomic replace. [System.IO.File]::Replace's third argument must be a real
        CLR null: PowerShell maps both $null and [string]::Empty to an empty Path
        for this overload, which .NET rejects with "The path is not of a legal
        form". Only NullString::Value passes real null. (probe_file_replace.ps1)
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination
    )
    if (Test-Path -LiteralPath $Destination) {
        [System.IO.File]::Replace($Source, $Destination,
            [System.Management.Automation.Language.NullString]::Value)
    } else {
        [System.IO.File]::Move($Source, $Destination)
    }
}

function Test-R2Manifest {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw "manifest not found: $Path" }
    $manifest = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($field in @("baseline_sha256", "patched_sha256", "formal_app_dir")) {
        if (-not $manifest.$field) { throw "manifest missing $field" }
    }
    return $manifest
}

