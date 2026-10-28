param(
  [int]$Port = 9223,
  [string]$UserDataDir = "$env:LOCALAPPDATA\HuoYan\EdgeCdpProfile",
  [Alias('ChromePath')][string]$EdgePath = "",
  [string]$Url = "https://www.taobao.com/",
  [switch]$RestoreLastSession
)

$ErrorActionPreference = 'Stop'
if (-not $EdgePath) {
  $candidates = @(
    'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
  )
  $EdgePath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $EdgePath -or -not (Test-Path -LiteralPath $EdgePath)) {
  throw 'Microsoft Edge executable not found. Pass -EdgePath explicitly.'
}

function Read-EdgeEndpoint {
  $response = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec 5
  if ($response.Browser -notmatch 'Edg/|Edge/') {
    throw "Port $Port is not a Microsoft Edge endpoint ($($response.Browser)). Choose a different port."
  }
  Write-Host "Browser: $($response.Browser)"
  Write-Host "CDP: http://127.0.0.1:$Port"
}

try {
  $existing = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec 2
} catch { $existing = $null }
if ($existing) {
  Read-EdgeEndpoint
  $running = @(Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" | Where-Object {
    $_.CommandLine -match "--remote-debugging-port=$Port(?:\s|$)" -and $_.CommandLine -notmatch '--type='
  })
  if ($running.Count -ne 1 -or $running[0].CommandLine -notmatch '--no-proxy-server' -or $running[0].CommandLine -notmatch '--enable-automation') {
    throw 'Existing Edge was not started in verified direct mode. Close/restart the HuoYan Edge session before using this script.'
  }
  Write-Host 'Existing Edge session reused; no new window created.'
  exit 0
}

$profileProcesses = @(Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" | Where-Object {
  $_.CommandLine -and $_.CommandLine.Contains($UserDataDir) -and $_.CommandLine -notmatch '--type='
})
if ($profileProcesses.Count) {
  throw 'HuoYan profile is already open without the requested CDP endpoint. Browser startup flags cannot be changed on that running window. Keep the current pages; close only the HuoYan window before switching modes.'
}
New-Item -ItemType Directory -Force -Path $UserDataDir | Out-Null
$arguments = @(
  "--remote-debugging-port=$Port",
  '--remote-debugging-address=127.0.0.1',
  '--no-proxy-server',
  '--enable-automation',
  "--user-data-dir=`"$UserDataDir`"",
  '--no-first-run',
  '--no-default-browser-check',
  $Url
)
# This window is interactive: the user logs in and handles site verification.
if ($RestoreLastSession) { $arguments += '--restore-last-session' }
Start-Process -FilePath $EdgePath -ArgumentList $arguments -WindowStyle Normal
for ($attempt = 0; $attempt -lt 10; $attempt++) {
  Start-Sleep -Milliseconds 500
  try { Read-EdgeEndpoint; Write-Host "Profile: $UserDataDir"; exit 0 }
  catch { if ($attempt -eq 9) { throw } }
}
