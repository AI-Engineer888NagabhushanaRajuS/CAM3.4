<#
.SYNOPSIS
  Build and run CAM 3.4 on this machine: the backend containers, the daemon (login + live progress) and the web UI.

.DESCRIPTION
  Idempotent: whatever already runs is left alone. Never deletes volumes or data.

    .\scripts\run-cam34.ps1            start everything, wait until it answers, print the URLs
    .\scripts\run-cam34.ps1 -Build     rebuild the service images first (a few minutes)
    .\scripts\run-cam34.ps1 -Status    show what is up, change nothing
    .\scripts\run-cam34.ps1 -Stop      stop the UI, the daemon and the containers (volumes are kept)

  Needs: Docker Desktop, Node + pnpm, Ollama on the host with qwen2.5-coder:7b (BOM mapping) plus qwen3:8b and
  nomic-embed-text (RFQ chat memory), and CAM-Source\.env (copy .env.example; POSTGRES_PASSWORD and JWT_SECRET
  must be set; the OpenRouter key is entered in the app's Settings). Logs: CAM-Source\.run\.
  If scripts are blocked: powershell -ExecutionPolicy Bypass -File scripts\run-cam34.ps1
#>
param(
    [switch]$Build,
    [switch]$Status,
    [switch]$Stop,
    [string]$Project = 'cam-e2e'   # the existing project name, so the existing volumes (database, inbox, exports) are reused
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$ui   = Join-Path $root 'accomplish-ui'
$logs = Join-Path $root '.run'
[void][System.IO.Directory]::CreateDirectory($logs)   # -LiteralPath everywhere: the folder name contains [3.4], a wildcard

$Core = 'postgres', 'temporal', 'temporal-worker', 'fastapi-router', 'hitl-router', 'upload-server', 'python-bridge',
        'reporting-mcp-server', 'intake-mcp-server', 'scrub-intake-mcp-server', 'gerber-integration-mcp-server',
        'distributor-pricing-mcp-server'
$WebPort = 5181
$DaemonPort = 9334

function Test-Port([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { return ($client.ConnectAsync('localhost', $Port).Wait(1500) -and $client.Connected) }
    catch { return $false }
    finally { $client.Close() }
}

function Stop-Port([int]$Port) {
    # netstat, not Get-NetTCPConnection: that cmdlet returns nothing in some restricted shells
    & netstat -ano -p tcp | ForEach-Object {
        if ($_ -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") { & taskkill /F /T /PID $Matches[1] | Out-Null }
    }
}

function Wait-Http([string]$Url, [int]$Seconds = 120) {
    $until = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $until) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -lt 500) { return $true }
        } catch {
            if ($_.Exception.Response) { return $true }   # 401/404 still means the server answered
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

function Compose {
    & docker compose -p $Project --project-directory $root -f (Join-Path $root 'docker-compose.yml') @args
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($args -join ' ') failed (exit $LASTEXITCODE)" }
}

function Show-Status {
    Write-Host "`nContainers (project $Project):"
    & docker ps -a --filter "label=com.docker.compose.project=$Project" --format "  {{.Names}}`t{{.Status}}" | Sort-Object
    Write-Host "`nHost processes:"
    foreach ($p in @(@{ n = 'Web UI'; port = $WebPort }, @{ n = 'Daemon'; port = $DaemonPort })) {
        $state = if (Test-Port $p.port) { 'listening' } else { 'NOT running' }
        Write-Host ("  {0,-8} :{1}  {2}" -f $p.n, $p.port, $state)
    }
}

if ($Status) { Show-Status; return }

if ($Stop) {
    Stop-Port $WebPort
    Stop-Port $DaemonPort
    Compose stop
    Write-Host 'Stopped. Volumes (database, inbox, exports) are untouched.'
    return
}

# ---- preflight ----
& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker is not running. Start Docker Desktop first.' }
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) { throw 'pnpm not found (needs Node 24 + pnpm).' }
$envFile = Join-Path $root '.env'
if (-not (Test-Path -LiteralPath $envFile)) { throw "Missing $envFile. Copy .env.example to .env and fill POSTGRES_PASSWORD, JWT_SECRET, OPENROUTER_API_KEY." }
$envText = Get-Content -LiteralPath $envFile -Raw
foreach ($key in 'POSTGRES_PASSWORD', 'JWT_SECRET') {
    if ($envText -notmatch "(?m)^$key=\S") { throw ".env has no value for $key." }
}
try {
    $tags = (Invoke-RestMethod -Uri 'http://localhost:11434/api/tags' -TimeoutSec 5).models.name
    foreach ($m in 'qwen2.5-coder:7b', 'qwen3:8b', 'nomic-embed-text:latest') {
        if (-not ($tags -contains $m)) { Write-Warning "Ollama is up but $m is missing: run  ollama pull $m" }
    }
} catch {
    Write-Warning 'Ollama is not answering on :11434. BOM header mapping needs it (ollama serve).'
}

# ---- backend containers ----
Write-Host "Starting backend containers ($Project)..."
if ($Build) { Compose up -d --build @Core } else { Compose up -d @Core }
try { Compose up -d temporal-ui } catch { Write-Warning "Temporal UI did not start (optional): $_" }

$checks = @(
    @{ n = 'upload server'; u = 'http://localhost:13100/openapi.json' },
    @{ n = 'tool router';   u = 'http://localhost:15100/openapi.json' },
    @{ n = 'HITL router';   u = 'http://localhost:15102/openapi.json' },
    @{ n = 'python bridge'; u = 'http://localhost:13110/openapi.json' }
)
foreach ($c in $checks) {
    if (-not (Wait-Http $c.u 180)) { throw "$($c.n) did not answer at $($c.u). See: docker logs for that container." }
}

# ---- daemon (login, live progress) and web UI, on the host ----
if ($Build) { Stop-Port $DaemonPort; Stop-Port $WebPort }   # -Build means "run what the source says now"
# Start-Process -WorkingDirectory treats the "[3.4]" in the repo path as a wildcard and fails: use .NET directly.
function Start-Hidden([string]$CmdLine, [string]$Out, [string]$Err) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'cmd.exe'
    $psi.Arguments = "/c $CmdLine 1>`"$Out`" 2>`"$Err`""
    $psi.WorkingDirectory = $ui
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    [void][System.Diagnostics.Process]::Start($psi)
}
if (-not (Test-Port $DaemonPort)) {
    Write-Host 'Starting the daemon...'
    $env:ACCOMPLISH_BACKEND_PORT = "$DaemonPort"
    $env:ACCOMPLISH_TEST_LOGIN = '1'
    Start-Hidden 'pnpm -F @accomplish/daemon dev' (Join-Path $logs 'daemon.log') (Join-Path $logs 'daemon.err.log')
}
if (-not (Test-Port $WebPort)) {
    Write-Host 'Starting the web UI...'
    Start-Hidden "pnpm dev:web --host 0.0.0.0 --port $WebPort --strictPort" (Join-Path $logs 'web.log') (Join-Path $logs 'web.err.log')
}
if (-not (Wait-Http "http://localhost:$DaemonPort/health" 180)) { throw "Daemon did not answer on :$DaemonPort. See $logs\daemon.log" }
if (-not (Wait-Http "http://localhost:$WebPort" 120)) { throw "Web UI did not answer on :$WebPort. See $logs\web.log" }

Show-Status
Write-Host @"

CAM 3.4 is up.
  App           http://localhost:$WebPort   (click "Sign in as Tester": digibull / srim-test-2026, dev login)
  Temporal UI   http://localhost:8082
  API docs      upload :13100/docs   router :15100/docs   HITL :15102/docs   bridge :13110/docs
  Stop          .\scripts\run-cam34.ps1 -Stop      (data is kept)
"@
