<#
.SYNOPSIS
  Install and manage HotStreak as a Windows service (via NSSM), so it starts with the PC and runs without anyone
  signed in.

.DESCRIPTION
  The service runs `python -m app --serve` in api\: one process that serves the built web app and the API on
  TRACKER_WEB_IP:TRACKER_WEB_PORT from .env. To try exactly that by hand, run `start --serve` instead (stop the
  service first; they use the same port).

  Run from an Administrator PowerShell, in the repo folder:

    powershell -ExecutionPolicy Bypass -File windows\service.ps1 install
    powershell -ExecutionPolicy Bypass -File windows\service.ps1 update      # after `git pull` or editing .env
    powershell -ExecutionPolicy Bypass -File windows\service.ps1 status

  Commands:
    install     set up (Python packages, npm packages, database, web build), register the service and start it
    update      stop, set up again (picks up new code, packages, migrations and .env), start
    start / stop / restart / status
    uninstall   stop and remove the service and its firewall rule (keeps the database, .env and logs)

  NSSM: pass -Nssm <path to nssm.exe>, put nssm.exe in this folder (windows\), or have it on PATH
  (`winget install NSSM.NSSM`, or download from https://nssm.cc).

  Logs go to logs\hotstreak.log in the repo folder (rotated at 10 MB).
#>
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet('install', 'update', 'uninstall', 'start', 'stop', 'restart', 'status')]
    [string]$Command,
    [string]$Name = 'HotStreak',
    [string]$Nssm
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Api = Join-Path $Root 'api'
$VenvPy = Join-Path $Api '.venv\Scripts\python.exe'
$Logs = Join-Path $Root 'logs'
$LogFile = Join-Path $Logs 'hotstreak.log'
$FirewallRule = "$Name web app"

function Ok($msg)   { Write-Host "  + $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  ! $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  x $msg" -ForegroundColor Red; exit 1 }
function Step($msg) { Write-Host $msg -ForegroundColor White }

function Find-Nssm {
    if ($Nssm) {
        if (-not (Test-Path $Nssm)) { Fail "nssm not found at $Nssm" }
        return (Resolve-Path $Nssm).Path
    }
    $local = Join-Path $PSScriptRoot 'nssm.exe'
    if (Test-Path $local) { return $local }
    $cmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    Fail "nssm.exe not found. Install it (winget install NSSM.NSSM), put it in $PSScriptRoot, or pass -Nssm <path>."
}

function Invoke-Nssm {
    & $script:NssmExe @args | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "nssm $($args -join ' ') failed (exit code $LASTEXITCODE)" }
}

function Test-Admin {
    $id = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    return $id.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-Service-Or-Null { Get-Service -Name $Name -ErrorAction SilentlyContinue }

function Invoke-Setup {
    # start.py checks the tools and .env, installs packages, migrates the database and builds the web app.
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { & py -3 (Join-Path $Root 'start.py') --setup }
    else { & python (Join-Path $Root 'start.py') --setup }
    if ($LASTEXITCODE -ne 0) { Fail "Setup failed; see above." }
}

function Get-Config {
    Push-Location $Api
    try {
        $json = & $VenvPy -c "import json; from app.config import settings as s; print(json.dumps({'ip': s.web_ip, 'port': s.web_port}))"
    } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { Fail "Couldn't read the settings from .env" }
    return $json | ConvertFrom-Json
}

function Get-LocalUrl($cfg) {
    $hostName = $cfg.ip
    if ($hostName -eq '0.0.0.0' -or $hostName -eq '::') { $hostName = 'localhost' }
    if ($hostName.Contains(':')) { $hostName = "[$hostName]" }
    return "http://${hostName}:$($cfg.port)"
}

function Set-Firewall($cfg) {
    Get-NetFirewallRule -DisplayName $FirewallRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    if ($cfg.ip -eq '127.0.0.1' -or $cfg.ip -eq 'localhost' -or $cfg.ip -eq '::1') {
        Ok "Local-only (TRACKER_WEB_IP=$($cfg.ip)); no firewall rule needed"
        return
    }
    New-NetFirewallRule -DisplayName $FirewallRule -Direction Inbound -Protocol TCP -LocalPort $cfg.port `
        -Action Allow -Profile Domain, Private | Out-Null
    Ok "Firewall allows TCP $($cfg.port) on private/domain networks"
}

function Wait-Healthy($cfg) {
    $url = "$(Get-LocalUrl $cfg)/api/health"
    for ($i = 0; $i -lt 60; $i++) {
        try {
            Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 | Out-Null
            Ok "Running: open $(Get-LocalUrl $cfg)"
            return
        } catch { Start-Sleep -Milliseconds 500 }
    }
    Fail "The service didn't answer at $url; see $LogFile"
}

function Start-App {
    $cfg = Get-Config
    Invoke-Nssm start $Name
    Wait-Healthy $cfg
}

function Wait-Stopped([int]$seconds) {
    for ($i = 0; $i -lt $seconds * 2; $i++) {
        $svc = Get-Service-Or-Null
        if (-not $svc -or $svc.Status -eq 'Stopped') { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# Python left running after the service stopped (the venv's python.exe is a launcher that starts the real one, which
# can outlive it) keeps the port and the database open. Kill whatever python still listens on the web port.
function Stop-Leftovers {
    try { $port = (Get-Config).port } catch { return }
    $owners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($id in $owners) {
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -like 'python*') {
            & taskkill /T /F /PID $id | Out-Null
            Warn "Killed leftover $($proc.ProcessName) (PID $id) on port $port"
        }
    }
}

function Stop-App {
    $svc = Get-Service-Or-Null
    if (-not $svc -or $svc.Status -eq 'Stopped') { Stop-Leftovers; return }
    $servicePid = (Get-CimInstance Win32_Service -Filter "Name='$Name'").ProcessId
    # Ask nicely without blocking: nssm sends Ctrl+C and waits up to AppStopMethodConsole (10 s) itself.
    try { $svc.Stop() } catch { }
    if (-not (Wait-Stopped 20)) {
        Warn "The service didn't stop within 20 seconds; killing it"
        if ($servicePid) { & taskkill /T /F /PID $servicePid | Out-Null }
        if (-not (Wait-Stopped 10)) { Fail "Couldn't stop '$Name'. Kill python.exe and nssm.exe in Task Manager and try again." }
    }
    Stop-Leftovers
    Ok "Stopped"
}

function Require-Service {
    if (-not (Get-Service-Or-Null)) { Fail "Service '$Name' isn't installed (windows\service.ps1 install)" }
}

if ($Command -ne 'status' -and -not (Test-Admin)) {
    Fail "Run this from an Administrator PowerShell."
}
$script:NssmExe = Find-Nssm

switch ($Command) {
    'install' {
        if (Get-Service-Or-Null) { Fail "Service '$Name' is already installed; use 'update' to apply changes." }
        Invoke-Setup
        $cfg = Get-Config

        Step "Service"
        New-Item -ItemType Directory -Force -Path $Logs | Out-Null
        Invoke-Nssm install $Name $VenvPy '-m' 'app' '--serve'
        Invoke-Nssm set $Name AppDirectory $Api
        Invoke-Nssm set $Name DisplayName 'HotStreak sales board'
        Invoke-Nssm set $Name Description 'HotStreak web app and API. Managed by windows\service.ps1 in the repo.'
        Invoke-Nssm set $Name Start SERVICE_DELAYED_AUTO_START
        Invoke-Nssm set $Name AppEnvironmentExtra 'PYTHONUNBUFFERED=1' 'PYTHONIOENCODING=utf-8'
        Invoke-Nssm set $Name AppStdout $LogFile
        Invoke-Nssm set $Name AppStderr $LogFile
        Invoke-Nssm set $Name AppRotateFiles 1
        Invoke-Nssm set $Name AppRotateOnline 1
        Invoke-Nssm set $Name AppRotateBytes 10485760
        # Ctrl+C first so uvicorn shuts down cleanly; restart after a crash.
        Invoke-Nssm set $Name AppStopMethodConsole 10000
        Invoke-Nssm set $Name AppKillProcessTree 1
        Invoke-Nssm set $Name AppExit Default Restart
        Invoke-Nssm set $Name AppRestartDelay 5000
        Ok "Service '$Name' installed (starts automatically with Windows)"
        Set-Firewall $cfg
        Start-App
    }
    'update' {
        Require-Service
        Step "Stopping"
        Stop-App  # packages and the database can't be updated while the service has them open
        Invoke-Setup
        Step "Service"
        Set-Firewall (Get-Config)
        Start-App
    }
    'uninstall' {
        Require-Service
        Stop-App
        Invoke-Nssm remove $Name confirm
        Get-NetFirewallRule -DisplayName $FirewallRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
        Ok "Service '$Name' removed (database, .env and logs kept)"
    }
    'start' { Require-Service; Start-App }
    'stop' { Require-Service; Stop-App }
    'restart' { Require-Service; Stop-App; Start-App }
    'status' {
        Require-Service
        $svc = Get-Service-Or-Null
        Write-Host "Service '$Name': $($svc.Status)"
        if ($svc.Status -eq 'Running') {
            $url = Get-LocalUrl (Get-Config)
            try {
                Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 3 | Out-Null
                Ok "Answering at $url"
            } catch { Warn "Not answering at $url; see $LogFile" }
        }
        Write-Host "Log: $LogFile"
    }
}
