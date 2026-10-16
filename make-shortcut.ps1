<#
.SYNOPSIS
    Put a desktop shortcut on your desktop that installs the patch.

.DESCRIPTION
    Creates "Install DSH session-window patch.lnk" pointing at install.cmd.
    Double-clicking that shortcut kills DeepSeek Harness, installs the patched
    shell, and waits for a keypress - so you never have to type a command after
    the app you were talking to has gone away.

.PARAMETER Desktop
    Where to place the shortcut. Defaults to your Desktop.
#>
[CmdletBinding()]
param([string]$Desktop = [Environment]::GetFolderPath("Desktop"))

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $here "install.cmd"
if (-not (Test-Path -LiteralPath $target)) {
    throw "install.cmd not found beside this script: $target"
}

$link = Join-Path $Desktop "Install DSH session-window patch.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $here
$shortcut.Description = "Install the DSH Desktop patch that opens a Session in a second window"
$shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,21"
$shortcut.Save()

Write-Host "Shortcut created:" -ForegroundColor Green
Write-Host "  $link"
Write-Host ""
Write-Host "When you are ready: close this session, then double-click that shortcut."
Write-Host "It kills DeepSeek Harness, installs the patch and waits for a keypress."
Write-Host ""
Write-Host "Remove it later with:  Remove-Item -LiteralPath '$link'"

