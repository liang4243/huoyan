param(
  [string]$UserDataDir = "$env:LOCALAPPDATA\HuoYan\EdgeCdpProfile",
  [string]$Url = 'about:blank',
  [switch]$KeepAlive
)
$ErrorActionPreference = 'Stop'
$EdgePath = @(
  'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
  'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
  "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $EdgePath) { throw 'Microsoft Edge executable not found.' }
function Get-ProfileProcess {
  @(Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains($UserDataDir) -and $_.CommandLine -notmatch '--type='
  })
}
$running = @(Get-ProfileProcess)
if ($running.Count -gt 1) { throw 'Multiple HuoYan profile processes found; no new window was started.' }
if ($running.Count -eq 1) {
  $existingCommandLine = $running[0].CommandLine
  if ($existingCommandLine -notmatch '--no-proxy-server' -or $existingCommandLine -match '--enable-automation|--remote-debugging-|--headless|--disable-blink-features') {
    throw 'HuoYan profile is open in a different mode. Preserve its pages and close that window before starting manual direct mode.'
  }
  Write-Output 'Existing manual direct HuoYan Edge reused; no navigation or new window.'
}
New-Item -ItemType Directory -Force -Path $UserDataDir | Out-Null
# Manual comparison only: no CDP, automation flag, browser-feature override or
# automatic site interaction. Uses the original HuoYan profile and direct mode.
$arguments = @('--no-proxy-server', "--user-data-dir=`"$UserDataDir`"", '--no-first-run', '--no-default-browser-check', $Url)
if (-not $running.Count) {
  Start-Process -FilePath $EdgePath -ArgumentList $arguments -WindowStyle Normal
  for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 500
    $running = @(Get-ProfileProcess)
    if ($running.Count) { break }
  }
}
if ($running.Count -ne 1) { throw 'Cannot verify the manual HuoYan Edge process.' }
$commandLine = $running[0].CommandLine
if ($commandLine -notmatch '--no-proxy-server' -or $commandLine -match '--enable-automation|--remote-debugging-|--headless|--disable-blink-features') {
  throw 'Unexpected browser configuration; manual comparison is not valid.'
}
Write-Output 'PASS manual visible Edge, original HuoYan profile, direct flag; no CDP or automation flags.'
if ($KeepAlive) {
  Write-Output 'Manual comparison window is ready; waiting for the user. No page automation is running.'
  do {
    Start-Sleep -Seconds 10
    $running = @(Get-ProfileProcess)
  } while ($running.Count)
  Write-Output 'Manual comparison window closed.'
}
