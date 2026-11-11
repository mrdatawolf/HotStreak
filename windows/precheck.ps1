<#
.SYNOPSIS
  Check that this PC has everything HotStreak needs, then offer to install it as a Windows service.

.DESCRIPTION
  Double-click install.cmd in the repo folder, or run:

    powershell -ExecutionPolicy Bypass -File windows\precheck.ps1

  Checks (nothing is installed or changed until you say yes):
    - Python 3.12+ from python.org (not the Microsoft Store one, which a service can't run)
    - Node.js 20+ and npm
    - NSSM (windows\nssm.exe or on PATH)
    - .env exists and has a break-glass password (offers to create it if it's missing)
    - the web port is free
    - whether the HotStreak service is already installed

  If everything passes, it asks whether to install the service now and runs windows\service.ps1 install, asking
  Windows for Administrator rights if needed. If the service is already installed, it offers 'update' instead.
#>
param([string]$Name = 'HotStreak')

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root '.env'
$EnvExample = Join-Path $Root '.env.example'
$ServiceScript = Join-Path $PSScriptRoot 'service.ps1'

$script:Problems = 0
function Ok($msg)   { Write-Host "  + $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  ! $msg" -ForegroundColor Yellow }
function Bad($msg, $fix) {
    Write-Host "  x $msg" -ForegroundColor Red
    if ($fix) { Write-Host "      $fix" -ForegroundColor Gray }
    $script:Problems++
}
function Step($msg) { Write-Host ""; Write-Host $msg -ForegroundColor White }

function Ask($question, [bool]$default = $true) {
    $hint = if ($default) { '[Y/n]' } else { '[y/N]' }
    $answer = Read-Host "$question $hint"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
    return $answer.Trim().ToLower().StartsWith('y')
}

function Test-Admin {
    $id = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    return $id.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Read-DotEnv($path) {
    $values = @{}
    if (-not (Test-Path $path)) { return $values }
    foreach ($line in Get-Content $path) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#') -or -not $t.Contains('=')) { continue }
        $key, $value = $t.Split('=', 2)
        $values[$key.Trim()] = $value.Trim().Trim('"').Trim("'")
    }
    return $values
}

# Runs a command and returns its output, or $null if it isn't there or fails.
function Invoke-Quietly([scriptblock]$cmd) {
    try {
        $out = & $cmd 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        return $out
    } catch { return $null }
}

Write-Host "HotStreak pre-install check" -ForegroundColor Cyan
Write-Host "Repo: $Root"

# --- Python ---

Step "Python"
$pyInfo = $null
$probe = "import sys; print('%d.%d.%d' % sys.version_info[:3]); print(sys.executable)"
if (Get-Command py -ErrorAction SilentlyContinue) { $pyInfo = Invoke-Quietly { py -3 -c $probe } }
if (-not $pyInfo -and (Get-Command python -ErrorAction SilentlyContinue)) { $pyInfo = Invoke-Quietly { python -c $probe } }

$pythonFix = 'Install Python 3.12+ from https://www.python.org/downloads/ (or: winget install Python.Python.3.12) and tick "Add python.exe to PATH". Then open a new window and run this again.'
if (-not $pyInfo) {
    Bad "Python not found" $pythonFix
} else {
    $pyVersion = [version]$pyInfo[0]
    $pyExe = $pyInfo[1]
    if ($pyExe -like '*\WindowsApps\*') {
        Bad "Python $pyVersion is the Microsoft Store version ($pyExe), which a Windows service can't run" $pythonFix
    } elseif ($pyVersion -lt [version]'3.12') {
        Bad "Python 3.12+ needed (found $pyVersion at $pyExe)" $pythonFix
    } else {
        Ok "Python $pyVersion ($pyExe)"
    }
}

# --- Node.js ---

Step "Node.js"
$nodeFix = 'Install Node.js 20+ (LTS) from https://nodejs.org (or: winget install OpenJS.NodeJS.LTS). Then open a new window and run this again.'
$nodeVersion = $null
if (Get-Command node -ErrorAction SilentlyContinue) { $nodeVersion = Invoke-Quietly { node --version } }
if (-not $nodeVersion) {
    Bad "Node.js not found" $nodeFix
} else {
    $nodeVersion = "$nodeVersion".Trim()
    $major = [int]($nodeVersion.TrimStart('v').Split('.')[0])
    if ($major -lt 20) { Bad "Node.js 20+ needed (found $nodeVersion)" $nodeFix }
    else { Ok "Node.js $nodeVersion" }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Bad "npm not found (it comes with Node.js; reinstall Node.js)" $nodeFix }
    else { Ok "npm found" }
}

# --- NSSM ---

Step "NSSM (runs HotStreak as a service)"
$nssmLocal = Join-Path $PSScriptRoot 'nssm.exe'
$nssmCmd = Get-Command nssm -ErrorAction SilentlyContinue
if (Test-Path $nssmLocal) { Ok "nssm.exe found in windows\" }
elseif ($nssmCmd) { Ok "nssm found ($($nssmCmd.Source))" }
else { Bad "NSSM not found" "Run: winget install NSSM.NSSM (then open a new window), or download it from https://nssm.cc and put nssm.exe in $PSScriptRoot" }

# --- Settings (.env) ---

Step "Settings (.env)"
if (-not (Test-Path $EnvFile)) {
    Warn ".env not found"
    if ((Test-Path $EnvExample) -and (Ask "  Create .env now with a random break-glass password?")) {
        $bytes = New-Object byte[] 24
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $password = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
        $network = Ask "  Should TVs and other PCs on the network be able to open HotStreak?"
        $content = Get-Content $EnvExample | ForEach-Object {
            if ($_ -match '^TRACKER_BREAKGLASS_PASSWORD=') { "TRACKER_BREAKGLASS_PASSWORD=$password" }
            elseif ($network -and $_ -match '^TRACKER_WEB_IP=') { 'TRACKER_WEB_IP=0.0.0.0' }
            else { $_ }
        }
        # UTF-8 without a BOM, so Python and Vite read the first line correctly.
        [IO.File]::WriteAllLines($EnvFile, [string[]]$content, (New-Object Text.UTF8Encoding $false))
        Ok ".env created"
        Write-Host ""
        Write-Host "  Break-glass sign-in (save this somewhere safe; it's also in .env):" -ForegroundColor Yellow
        Write-Host "    username: breakglass"
        Write-Host "    password: $password"
    } else {
        Bad ".env missing" "Copy .env.example to .env and set TRACKER_BREAKGLASS_PASSWORD."
    }
}

$envValues = Read-DotEnv $EnvFile
$webIp = if ($envValues['TRACKER_WEB_IP']) { $envValues['TRACKER_WEB_IP'] } else { '127.0.0.1' }
$webPort = if ($envValues['TRACKER_WEB_PORT']) { [int]$envValues['TRACKER_WEB_PORT'] } else { 5190 }
if (Test-Path $EnvFile) {
    Ok ".env found"
    if ($envValues['TRACKER_BREAKGLASS_PASSWORD']) { Ok "Break-glass password set" }
    else { Warn "TRACKER_BREAKGLASS_PASSWORD is empty, so break-glass sign-in is off. You'll need it for the first sign-in." }
    if ($webIp -in @('127.0.0.1', 'localhost', '::1')) {
        Warn "TRACKER_WEB_IP=${webIp}: only this PC can open HotStreak. Set it to 0.0.0.0 in .env for TVs and other PCs."
    } else {
        Ok "Reachable from the network on port $webPort (TRACKER_WEB_IP=$webIp)"
    }
}

# --- Service and port ---

Step "Service"
$svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
if ($svc) {
    Ok "Service '$Name' is already installed ($($svc.Status))"
} else {
    Ok "Service '$Name' isn't installed yet"
    $listener = Get-NetTCPConnection -State Listen -LocalPort $webPort -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        $proc = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
        $who = if ($proc) { "$($proc.ProcessName), PID $($proc.Id)" } else { "PID $($listener.OwningProcess)" }
        Bad "Port $webPort is already in use ($who)" "Close that program (a 'start' window left open?), or change TRACKER_WEB_PORT in .env."
    } else {
        Ok "Port $webPort is free"
    }
}

# --- Result ---

Write-Host ""
if ($script:Problems -gt 0) {
    Write-Host "$($script:Problems) problem(s) found. Fix the items marked x above, then run this again." -ForegroundColor Red
    exit 1
}

Write-Host "All checks passed." -ForegroundColor Green
Write-Host ""
$command = if ($svc) { 'update' } else { 'install' }
if ($svc) {
    Write-Host "HotStreak is already a service. 'update' stops it, installs packages, migrates the database,"
    Write-Host "rebuilds the web app and starts it again (use this after a git pull or editing .env)."
} else {
    Write-Host "Next, HotStreak can be installed as a Windows service. It will start with Windows, run without anyone"
    Write-Host "signed in, and restart itself if it crashes. This installs the Python and npm packages, sets up the"
    Write-Host "database and builds the web app, which takes a few minutes the first time."
}
Write-Host ""
Write-Host "To do it yourself later, from an Administrator PowerShell in $Root :"
Write-Host "  powershell -ExecutionPolicy Bypass -File windows\service.ps1 $command" -ForegroundColor Gray
Write-Host ""

$question = if ($svc) { "Update the '$Name' service now?" } else { "Install HotStreak as a service now?" }
if (-not (Ask $question)) {
    Write-Host "Nothing changed."
    exit 0
}

if (Test-Admin) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $ServiceScript $command -Name $Name
    exit $LASTEXITCODE
}

# Not elevated: run service.ps1 in a new Administrator window and keep it open so the result can be read.
Write-Host "Asking Windows for Administrator rights; the install runs in a new window."
$inner = "& '$ServiceScript' $command -Name '$Name'; Write-Host ''; Read-Host 'Press Enter to close'"
try {
    Start-Process powershell -Verb RunAs -WorkingDirectory $Root `
        -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $inner
} catch {
    Write-Host "Administrator rights were refused. Run the command above from an Administrator PowerShell instead." -ForegroundColor Red
    exit 1
}
