# -*- coding: utf-8 -*-
<#
  Наблюдатель интернета (01.10.2026, по просьбе владельца): тихо пишет
  связность в watch-internet.log, чтобы ПОСЛЕ падения было с чем свериться.
  Ничего не меняет в системе - только пробы и чтение статусов.

  Пробы каждые $IntervalSec: TCP 1.1.1.1:443, TCP 8.8.8.8:53, DNS-резолв,
  ICMP до шлюза. В лог попадают: старт, СМЕНЫ состояния (при FAIL - полный
  снимок: адаптеры, TUN, маршруты, прокси, VPN-процессы) и heartbeat каждые
  30 мин. Файл крутится на 4 МБ (старый - watch-internet.log.old).

  Запуск: задача «VPNLauncher-InternetWatch» (AtLogon, скрыто) либо вручную
  powershell -File tools\internet-watch.ps1
#>
param(
    [int]$IntervalSec = 30,
    [string]$LogPath = (Join-Path $PSScriptRoot '..\watch-internet.log')
)

$ErrorActionPreference = 'SilentlyContinue'

function Write-Line([string]$Text) {
    $dir = Split-Path -Parent $LogPath
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
    if ((Test-Path $LogPath) -and ((Get-Item $LogPath).Length -gt 4MB)) {
        Move-Item -Force $LogPath ($LogPath + '.old')
    }
    Add-Content -Path $LogPath -Encoding UTF8 -Value $Text
}

function Probe-Tcp([string]$Ip, [int]$Port, [int]$ToMs = 2500) {
    $c = New-Object System.Net.Sockets.TcpClient
    try {
        $ar = $c.BeginConnect($Ip, $Port, $null, $null)
        $done = $ar.AsyncWaitHandle.WaitOne($ToMs)
        if ($done -and $c.Connected) { return 'OK' }
        if ($done) { return 'REFUSED' }
        return 'TIMEOUT'
    } catch {
        return 'ERR'
    } finally {
        try { $c.Close() } catch { }
    }
}

function Probe-Dns {
    try {
        $r = Resolve-DnsName -Name www.google.com -Type A -QuickTimeout -DnsOnly -ErrorAction Stop
        if ($r | Where-Object { $_.IPAddress }) { return 'OK' }
        return 'EMPTY'
    } catch {
        return 'FAIL'
    }
}

function Probe-Ping([string]$Ip) {
    if (-not $Ip) { return 'NO-GW' }
    try {
        $p = New-Object System.Net.NetworkInformation.Ping
        $r = $p.Send($Ip, 1200)
        if ($r.Status -eq 'Success') { return 'OK' }
        return "$($r.Status)"
    } catch {
        return 'ERR'
    }
}

function Get-Gw {
    $r = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' `
        -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1
    if ($r) { return $r.NextHop }
    return $null
}

function Get-Snapshot {
    $lines = @()
    $ad = (Get-NetAdapter -ErrorAction SilentlyContinue |
        ForEach-Object { "$($_.Name):$($_.Status)" }) -join ', '
    $lines += "    adapters: $ad"
    $tun = Get-NetAdapter -Name '*tun*' -ErrorAction SilentlyContinue
    $lines += "    tun: " + $(if ($tun) {
            ($tun | ForEach-Object { "$($_.Name):$($_.Status)" }) -join ','
        } else { 'no' })
    $rt = (Get-NetRoute -AddressFamily IPv4 `
            -DestinationPrefix '0.0.0.0/0', '0.0.0.0/1', '128.0.0.0/1' `
            -ErrorAction SilentlyContinue |
        ForEach-Object { "$($_.DestinationPrefix)>$($_.NextHop)/$($_.InterfaceAlias)" }) -join '; '
    $lines += "    routes: $rt"
    $pr = Get-ItemProperty `
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' `
        -ErrorAction SilentlyContinue
    $lines += "    proxy: enable=$($pr.ProxyEnable) server=$($pr.ProxyServer)"
    $procs = (Get-Process VPNLauncher, sing-box -ErrorAction SilentlyContinue |
        ForEach-Object { "$($_.Name):$($_.Id)" }) -join ','
    if (-not $procs) { $procs = '-' }
    $lines += "    vpn-procs: $procs"
    return $lines
}

Write-Line ("$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  WATCH started " +
    "(interval ${IntervalSec}s, log: $LogPath)")

$state = ''
$failSince = $null
$beat = 0

while ($true) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $gw = Get-Gw
    $tcpExt = Probe-Tcp '1.1.1.1' 443
    $tcpDns = Probe-Tcp '8.8.8.8' 53
    $dns = Probe-Dns
    $pingGw = Probe-Ping $gw

    $netOk = ($tcpExt -eq 'OK' -or $tcpDns -eq 'OK') -and ($dns -eq 'OK')
    $newState = if ($netOk) { 'ok' } else { 'FAIL' }
    $brief = "tcp443=$tcpExt tcp53=$tcpDns dns=$dns ping-gw=$pingGw"
    $beat++

    if ($newState -ne $state) {
        if ($newState -eq 'FAIL') {
            $failSince = $ts
            Write-Line "$ts  STATE FAIL ($brief)"
            Get-Snapshot | ForEach-Object { Write-Line $_ }
        } else {
            $dur = ''
            if ($failSince) {
                $d0 = [datetime]::ParseExact($failSince, 'yyyy-MM-dd HH:mm:ss', $null)
                $dur = " after $([int]((Get-Date) - $d0).TotalSeconds)s"
                $failSince = $null
            }
            Write-Line "$ts  STATE ok$dur ($brief)"
        }
        $state = $newState
    } elseif ($beat % 60 -eq 0) {
        # heartbeat каждые ~30 мин - видно, что наблюдатель жив
        Write-Line "$ts  beat $state ($brief)"
    }

    Start-Sleep -Seconds $IntervalSec
}
