param(
  [int]$Port = 9222,
  [string]$UserDataDir = "$env:LOCALAPPDATA\HuoYan\ChromeCdpProfile",
  [string]$ChromePath = '',
  [string]$Url = 'about:blank',
  [switch]$RestoreSession = $true,
  [switch]$FreshSession,
  [switch]$KeepAlive
)
$ErrorActionPreference = 'Stop'
if (-not $ChromePath) {
  $ChromePath = @('C:\Program Files\Google\Chrome\Application\chrome.exe',
    'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $ChromePath) { throw 'Google Chrome not found. Pass -ChromePath.' }
$existing = $null
try { $existing = Invoke-RestMethod "http://127.0.0.1:$Port/json/version" -TimeoutSec 2 } catch {}
$owned = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object {
  $_.CommandLine -and $_.CommandLine.Contains($UserDataDir) -and $_.CommandLine -notmatch '--type='
})
if ($existing) {
  if ($existing.Browser -notmatch '^Chrome/' -or $owned.Count -ne 1 -or
    $owned[0].CommandLine -notmatch "--remote-debugging-port=$Port(?:\s|$)" -or
    $owned[0].CommandLine -notmatch '--no-proxy-server') { throw 'Port is occupied by an unverified session. No browser was closed or replaced.' }
  Write-Output 'Existing HuoYan Chrome reused; no new tab opened.'
} else {
  if ($owned.Count) { throw 'HuoYan Chrome profile is already open with different startup parameters; no other window was closed.' }
  New-Item -ItemType Directory -Force -Path $UserDataDir | Out-Null
  $browserArguments = @("--remote-debugging-port=$Port",'--remote-debugging-address=127.0.0.1',
    '--no-proxy-server',"--user-data-dir=`"$UserDataDir`"",
    '--no-first-run','--no-default-browser-check')
  if ($RestoreSession -and -not $FreshSession) { $browserArguments += '--restore-last-session' }
  else { $browserArguments += $Url }
  Start-Process -FilePath $ChromePath -ArgumentList $browserArguments -WindowStyle Normal
  $ready = $false
  for ($attempt=0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 500
    try { $version = Invoke-RestMethod "http://127.0.0.1:$Port/json/version" -TimeoutSec 2; if ($version.Browser -match '^Chrome/') { $ready=$true; break } } catch {}
  }
  if (-not $ready) { throw 'Chrome CDP did not become ready; no automatic relaunch.' }
}
Write-Output "Chrome CDP ready: http://127.0.0.1:$Port; direct mode enabled."
try {
  $pageInventory = @(Invoke-RestMethod "http://127.0.0.1:$Port/json/list" -TimeoutSec 2 | Where-Object { $_.type -eq 'page' })
  $shoppingPages = @($pageInventory | Where-Object { $_.url -match '^https://(?:[^/]+\.)?(?:taobao|tmall)\.com(?:/|$)' })
  Write-Output "Existing shopping tabs observed: $($shoppingPages.Count). Login and page readiness require a live shopping_state check."
  if (-not $shoppingPages.Count) { Write-Output 'No shopping tab observed yet. Session restoration is not confirmed; no saved product URLs were reopened.' }
} catch { Write-Output 'Tab inventory unavailable; CDP readiness does not confirm session restoration.' }
if ($KeepAlive) {
  Write-Output 'Keeping the browser launcher session alive; close the HuoYan Chrome window to finish.'
  while ($true) {
    Start-Sleep -Seconds 15
    $running = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object {
      $_.CommandLine -and $_.CommandLine.Contains($UserDataDir) -and $_.CommandLine -notmatch '--type='
    })
    if (-not $running.Count) { break }
  }
}
