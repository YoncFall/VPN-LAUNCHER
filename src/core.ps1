# core.ps1 - парсер подписок + генерация конфига sing-box
# Движок: sing-box (SagerNet), GPL-3.0, отдельный внешний процесс.

Set-StrictMode -Off
$ErrorActionPreference = 'Stop'

# Скрипты лежат в <install>\src, движок и данные - на уровень выше
$script:InstallRoot = Split-Path -Parent $PSScriptRoot
$script:VpnRoot = $PSScriptRoot
$script:SingBox = Join-Path $script:InstallRoot 'sing-box.exe'
$script:StateFile = Join-Path $script:InstallRoot 'state.json'
$script:ConfigFile = Join-Path $script:InstallRoot 'config.json'
$script:LogFile = Join-Path $script:InstallRoot 'vpn-launcher.log'
$script:SocksPort = 20808

# ---------------- утилиты ----------------

function Write-VpnLog([string]$m) {
    $line = '{0}  {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m
    try {
        if ((Get-Item $script:LogFile -ErrorAction SilentlyContinue).Length -gt 2MB) {
            Remove-Item $script:LogFile -Force -ErrorAction SilentlyContinue
        }
        Add-Content -Path $script:LogFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch { }
}

function ConvertFrom-B64Utf8([string]$s) {
    if (-not $s) { return '' }
    $t = $s.Trim() -replace '\s', ''
    $t = $t -replace '-', '+' -replace '_', '/'
    switch ($t.Length % 4) {
        2 { $t += '==' }
        3 { $t += '=' }
        1 { return '' }
    }
    try {
        return [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($t))
    } catch { return '' }
}

function ConvertTo-B64Utf8([string]$s) {
    return [System.Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($s))
}

function Split-Uri([string]$uri) {
    # -> @{ Scheme; Body; Query; Fragment }
    $res = @{ Scheme = ''; Body = ''; Query = ''; Fragment = '' }
    $rest = $uri.Trim()
    $i = $rest.IndexOf('://')
    if ($i -lt 0) { return $res }
    $res.Scheme = $rest.Substring(0, $i).ToLower()
    $rest = $rest.Substring($i + 3)

    $h = $rest.IndexOf('#')
    if ($h -ge 0) { $res.Fragment = [uri]::UnescapeDataString($rest.Substring($h + 1)); $rest = $rest.Substring(0, $h) }

    $q = $rest.IndexOf('?')
    if ($q -ge 0) { $res.Query = $rest.Substring($q + 1); $rest = $rest.Substring(0, $q) }

    $res.Body = $rest
    return $res
}

function ConvertFrom-QueryString([string]$q) {
    $h = @{}
    if (-not $q) { return $h }
    foreach ($pair in ($q -split '&')) {
        if (-not $pair) { continue }
        $p = $pair -split '=', 2
        $k = [uri]::UnescapeDataString($p[0])
        $v = if ($p.Count -gt 1) { [uri]::UnescapeDataString($p[1]) } else { '' }
        if ($k) { $h[$k] = $v }
    }
    return $h
}

function Split-HostPort([string]$s) {
    # поддержка IPv6 в квадратных скобках
    if ($s -match '^\[(?<h>.+)\]:(?<p>\d+)$') { return @{ Host = $Matches.h; Port = [int]$Matches.p } }
    if ($s -match '^(?<h>.+):(?<p>\d+)$') { return @{ Host = $Matches.h; Port = [int]$Matches.p } }
    return @{ Host = $s; Port = 443 }
}

function Get-QueryVal($q, [string[]]$names, [string]$def = '') {
    foreach ($n in $names) {
        if ($q.ContainsKey($n) -and $q[$n] -ne '') { return $q[$n] }
    }
    return $def
}

function Get-BoolVal($q, [string[]]$names, [bool]$def = $false) {
    $v = Get-QueryVal $q $names ''
    if ($v -eq '') { return $def }
    return ($v -match '^(1|true|yes|on)$')
}

function New-TlsBlock($q, [string]$defaultSni, [bool]$tlsByDefault) {
    # -> hashtable или $null
    $sec = (Get-QueryVal $q @('security') '').ToLower()
    $isReality = ($sec -eq 'reality')
    $enabled = $tlsByDefault -or $sec -eq 'tls' -or $isReality
    if (-not $enabled) { return $null }

    $sni = Get-QueryVal $q @('sni', 'peer', 'host') $defaultSni
    $fp = Get-QueryVal $q @('fp') ''
    $insec = Get-BoolVal $q @('allowInsecure', 'insecure', 'allow_insecure') $false
    $alpn = Get-QueryVal $q @('alpn') ''

    $tls = [ordered]@{
        enabled = $true
        server_name = $sni
    }
    if ($insec) { $tls['insecure'] = $true }
    if ($fp) { $tls['utls'] = @{ enabled = $true; fingerprint = $fp } }
    if ($alpn) { $tls['alpn'] = @($alpn -split ',') }

    if ($isReality) {
        $pbk = Get-QueryVal $q @('pbk', 'public-key', 'publicKey') ''
        $sid = Get-QueryVal $q @('sid', 'short-id', 'shortId') ''
        $r = [ordered]@{ enabled = $true }
        if ($pbk) { $r['public_key'] = $pbk }
        if ($sid) { $r['short_id'] = $sid }
        $tls['reality'] = $r
        if (-not $sni) { $tls['server_name'] = (Get-QueryVal $q @('host') '') }
    }
    return $tls
}

function New-TransportBlock($q, [string]$defaultHost) {
    # -> hashtable или $null
    $net = (Get-QueryVal $q @('type', 'net', 'network', 'obfs') 'tcp').ToLower()
    $path = Get-QueryVal $q @('path') ''
    $hst = Get-QueryVal $q @('host') $defaultHost
    $svc = Get-QueryVal $q @('serviceName', 'servicename') ''
    $mode = Get-QueryVal $q @('mode') ''
    $hType = Get-QueryVal $q @('headerType') ''

    switch ($net) {
        'ws' {
            $t = [ordered]@{ type = 'ws' }
            if ($path) { $t['path'] = $path }
            if ($hst) { $t['headers'] = @{ Host = $hst } }
            return $t
        }
        'websocket' {
            $t = [ordered]@{ type = 'ws' }
            if ($path) { $t['path'] = $path }
            if ($hst) { $t['headers'] = @{ Host = $hst } }
            return $t
        }
        'grpc' {
            $t = [ordered]@{ type = 'grpc' }
            if ($svc) { $t['service_name'] = $svc }
            return $t
        }
        'h2' { $t = [ordered]@{ type = 'http' }; if ($hst) { $t['host'] = @($hst -split ',') }; if ($path) { $t['path'] = $path }; return $t }
        'http' {
            if ($hType -eq 'http') {
                $t = [ordered]@{ type = 'http' }
                if ($path) { $t['path'] = @($path -split ',') }
                if ($hst) { $t['host'] = @($hst -split ',') }
                return $t
            }
            return $null
        }
        'httpupgrade' {
            $t = [ordered]@{ type = 'httpupgrade'; host = $hst }
            if ($path) { $t['path'] = $path }
            return $t
        }
        'quic' { return @{ type = 'quic' } }
        default { return $null }
    }
}

# ---------------- парсеры протоколов ----------------

function ConvertFrom-ProxyUri([string]$uri, [int]$index) {
    $u = Split-Uri $uri
    $name = $u.Fragment
    $tag = 'node-{0}' -f $index
    if (-not $name) { $name = $tag }

    try {
        switch ($u.Scheme) {

            'vless' {
                $body = $u.Body
                $at = $body.LastIndexOf('@')
                if ($at -lt 0) { return $null }
                $uuid = $body.Substring(0, $at)
                $hp = Split-HostPort $body.Substring($at + 1)
                $q = ConvertFrom-QueryString $u.Query

                $ob = [ordered]@{
                    type = 'vless'
                    tag = $tag
                    server = $hp.Host
                    server_port = $hp.Port
                    uuid = $uuid
                }
                $flow = Get-QueryVal $q @('flow') ''
                if ($flow) { $ob['flow'] = $flow }
                $tls = New-TlsBlock $q $hp.Host $false
                if ($tls) { $ob['tls'] = $tls }
                $tr = New-TransportBlock $q $hp.Host
                if ($tr) { $ob['transport'] = $tr }
                return $ob
            }

            'vmess' {
                # vmess://base64(json)
                $raw = ConvertFrom-B64Utf8 $u.Body
                if (-not $raw -or -not $raw.TrimStart().StartsWith('{')) { return $null }
                $j = $raw | ConvertFrom-Json

                $srv = if ($j.add) { $j.add } else { $j.address }
                if (-not $srv) { return $null }
                $port = if ($j.port) { [int]$j.port } else { 443 }
                $uuid = if ($j.id) { $j.id } else { $j.ps }

                $ob = [ordered]@{
                    type = 'vmess'
                    tag = $tag
                    server = $srv
                    server_port = $port
                    uuid = $uuid
                    alter_id = 0
                }
                if ($j.aid -and [int]$j.aid -gt 0) { $ob['alter_id'] = [int]$j.aid }
                if ($j.ps) { $name = $j.ps }

                $q = @{}
                foreach ($k in @('net', 'type', 'host', 'path', 'tls', 'sni', 'alpn', 'fp', 'scy')) {
                    if ($j.PSObject.Properties.Name -contains $k -and $j.$k) { $q[$k] = $j.$k }
                }
                if ($j.tls -eq 'tls' -or $j.tls -eq 'reality') {
                    $q['security'] = $j.tls
                    $qs = "security=$($j.tls)"
                    if ($j.sni) { $qs += "&sni=$($j.sni)" }
                    if ($j.fp) { $qs += "&fp=$($j.fp)" }
                    if ($j.alpn) { $qs += "&alpn=$($j.alpn)" }
                    $q = ConvertFrom-QueryString $qs
                    $tls = New-TlsBlock $q $srv $false
                    if ($tls) { $ob['tls'] = $tls }
                }
                $tr = New-TransportBlock $q $srv
                if ($tr) { $ob['transport'] = $tr }
                return $ob
            }

            'trojan' {
                $body = $u.Body
                $at = $body.LastIndexOf('@')
                if ($at -lt 0) { return $null }
                $pw = $body.Substring(0, $at)
                $hp = Split-HostPort $body.Substring($at + 1)
                $q = ConvertFrom-QueryString $u.Query

                $ob = [ordered]@{
                    type = 'trojan'
                    tag = $tag
                    server = $hp.Host
                    server_port = $hp.Port
                    password = $pw
                }
                $tls = New-TlsBlock $q $hp.Host $true
                if ($tls) { $ob['tls'] = $tls }
                $tr = New-TransportBlock $q $hp.Host
                if ($tr) { $ob['transport'] = $tr }
                return $ob
            }

            'ss' {
                $body = $u.Body
                $plugin = $null
                $hasAt = $body.Contains('@')

                if ($hasAt) {
                    $at = $body.LastIndexOf('@')
                    $userinfo = $body.Substring(0, $at)
                    $hp = Split-HostPort $body.Substring($at + 1)
                    $plain = ConvertFrom-B64Utf8 $userinfo
                    if ($plain -notmatch ':') { $plain = $userinfo }
                } else {
                    $dec = ConvertFrom-B64Utf8 $body
                    if ($dec -notmatch '@') { return $null }
                    $at = $dec.LastIndexOf('@')
                    $plain = $dec.Substring(0, $at)
                    $hp = Split-HostPort $dec.Substring($at + 1)
                }

                $ci = $plain.IndexOf(':')
                if ($ci -lt 0) { return $null }
                $method = $plain.Substring(0, $ci)
                $pass = $plain.Substring($ci + 1)

                $q = ConvertFrom-QueryString $u.Query
                $ob = [ordered]@{
                    type = 'shadowsocks'
                    tag = $tag
                    server = $hp.Host
                    server_port = $hp.Port
                    method = $method
                    password = $pass
                }
                if ($q.Contains('plugin')) {
                    $pl = $q['plugin']
                    if ($pl -match 'obfs-local') { $ob['plugin'] = 'obfs-local'; $ob['plugin_opts'] = "obfs=http;obfs-host=$($q['plugin-opts'])" }
                    elseif ($pl -match 'v2ray-plugin') { $ob['plugin'] = 'v2ray-plugin'; $ob['plugin_opts'] = "mode=websocket" }
                }
                return $ob
            }

            { $_ -in @('hysteria2', 'hy2') } {
                $body = $u.Body
                $at = $body.LastIndexOf('@')
                $pw = if ($at -ge 0) { $body.Substring(0, $at) } else { '' }
                $hp = if ($at -ge 0) { Split-HostPort $body.Substring($at + 1) } else { Split-HostPort $body }
                $q = ConvertFrom-QueryString $u.Query

                $ob = [ordered]@{
                    type = 'hysteria2'
                    tag = $tag
                    server = $hp.Host
                    server_port = $hp.Port
                    password = $pw
                }
                $sni = Get-QueryVal $q @('sni', 'peer') $hp.Host
                $insec = Get-BoolVal $q @('insecure', 'allowInsecure') $false
                $ob['tls'] = @{ enabled = $true; server_name = $sni }
                if ($insec) { $ob['tls']['insecure'] = $true }
                $alpn = Get-QueryVal $q @('alpn') ''
                if ($alpn) { $ob['tls']['alpn'] = @($alpn -split ',') }

                $obfs = Get-QueryVal $q @('obfs') ''
                $obfsPw = Get-QueryVal $q @('obfs-password', 'obfs_password') ''
                if (-not $obfsPw) { $obfsPw = Get-QueryVal $q @('obfsParam') '' }
                if ($obfs -and $obfsPw) { $ob['obfs'] = @{ type = 'salamander'; password = $obfsPw } }
                return $ob
            }

            'tuic' {
                $body = $u.Body
                $at = $body.LastIndexOf('@')
                if ($at -lt 0) { return $null }
                $cred = $body.Substring(0, $at)
                $hp = Split-HostPort $body.Substring($at + 1)
                $q = ConvertFrom-QueryString $u.Query
                $ci = $cred.IndexOf(':')
                $uuid = if ($ci -ge 0) { $cred.Substring(0, $ci) } else { $cred }
                $pw = if ($ci -ge 0) { $cred.Substring($ci + 1) } else { '' }

                $ob = [ordered]@{
                    type = 'tuic'
                    tag = $tag
                    server = $hp.Host
                    server_port = $hp.Port
                    uuid = $uuid
                    password = $pw
                    congestion_control = (Get-QueryVal $q @('congestion_control') 'bbr')
                }
                $sni = Get-QueryVal $q @('sni', 'peer') $hp.Host
                $insec = Get-BoolVal $q @('insecure', 'allowInsecure') $false
                $ob['tls'] = @{ enabled = $true; server_name = $sni }
                if ($insec) { $ob['tls']['insecure'] = $true }
                $alpn = Get-QueryVal $q @('alpn') ''
                if ($alpn) { $ob['tls']['alpn'] = @($alpn -split ',') }
                return $ob
            }

            'http' { return $null }
            'socks' { return $null }
        }
    } catch {
        Write-VpnLog ("parse error [{0}] {1}: {2}" -f $u.Scheme, $uri.Substring(0, [Math]::Min(60, $uri.Length)), $_.Exception.Message)
        return $null
    }
    return $null
}

# ---------------- загрузка подписки ----------------

function Get-SubscriptionNodes([string]$url) {
    if (-not $url) { throw 'Пустая ссылка на подписку' }

    # локальный файл с подпиской (например подписка-зеркало .txt)
    if ($url -notmatch '^(https?|file)://') {
        $p = $url.Trim('"')
        if (Test-Path -LiteralPath $p -PathType Leaf) {
            $body = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $p), [Text.Encoding]::UTF8)
            Write-VpnLog ("fetching subscription from local file: " + $p)
            return (Parse-NodeList $body)
        }
        throw 'Нужна http(s)-ссылка либо путь к локальному файлу подписки'
    }
    if ($url -match '^file://') {
        $p = [uri]::UnescapeDataString($url.Substring(7))
        $body = [IO.File]::ReadAllText($p, [Text.Encoding]::UTF8)
        Write-VpnLog ("fetching subscription from local file: " + $p)
        return (Parse-NodeList $body)
    }

    $uHost = try { ([uri]$url).Host } catch { '?' }
    Write-VpnLog ("fetching subscription from host: " + $uHost)

    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add('User-Agent', 'sing-box/1.14.2')
    $body = $null
    try { $body = $wc.DownloadString($url) } finally { $wc.Dispose() }
    if (-not $body) { throw 'Пустой ответ сервера подписки' }
    return (Parse-NodeList $body)
}

# Разбирает уже скачанный текст подписки (или локальный файл) в список нод.
function Parse-NodeList([string]$body) {
    if (-not $body) { throw 'Пустой текст подписки' }

    # если это base64 - декодируем
    $t = ($body -replace '\s', '')
    if ($t -notmatch '^(vless|vmess|trojan|ss|hysteria2|hy2|tuic)://') {
        $dec = ConvertFrom-B64Utf8 $t
        if ($dec -match '://') { $body = $dec } else { $body = $t }
    }

    $lines = @($body -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '://' })
    $nodes = New-Object System.Collections.ArrayList
    $i = 0
    foreach ($l in $lines) {
        $i++
        $o = ConvertFrom-ProxyUri $l $i
        if ($o) {
            $disp = Split-Uri $l
            $o['display'] = if ($disp.Fragment) { $disp.Fragment } else { "$($o['server']):$($o['server_port'])" }
            $o['proto'] = $o['type']
            [void]$nodes.Add($o)
        }
    }
    Write-VpnLog ("  parsed {0} of {1} lines" -f $nodes.Count, $lines.Count)
    if ($nodes.Count -eq 0) { throw 'Не удалось распознать ни одного сервера в подписке' }
    return $nodes
}

# ---------------- генерация конфига ----------------

# Процессы, которые ВСЕГДА идут напрямую, минуя туннель.
# Игры и античиты не должны видеть подмену маршрута/адреса, а Steam и EAC/BE
# не должны получать соединения из-за VPN. Список нельзя потерять - он в коде.
$script:GameSafeProcesses = @(
    'steam.exe', 'steamwebhelper.exe', 'steamservice.exe', 'steamerrorreporter.exe', 'gameoverlayui64.exe',
    'RustClient.exe', 'Rust.exe', 'UnityCrashHandler64.exe',
    'EasyAntiCheat.exe', 'EasyAntiCheat_EOS.exe', 'EasyAntiCheat_Setup.exe', 'EACLauncher.exe',
    'DayZ_x64.exe', 'DayZDiag_x64.exe', 'DayZLauncher.exe', 'DayZ_BE.exe', 'BEService_x64.exe', 'DayZServer_x64.exe',
    'Phasmophobia.exe', 'REPO.exe', 'ONCE_HUMAN.exe',
    'GTA5.exe', 'GTA5_3258.exe', 'ragemp_v.exe', 'cs2.exe'
)

function New-SingBoxConfig {
    param(
        [Parameter(Mandatory)] $Nodes,
        [string[]]$Selected = @(),
        [ValidateSet('tun', 'proxy')] [string]$Mode = 'tun',
        [string[]]$AppList = @(),
        [string]$TestUrl = 'https://www.gstatic.com/generate_204',
        [switch]$OnlySelected
    )

    $out = New-Object System.Collections.ArrayList
    $tags = New-Object System.Collections.ArrayList

    $pool = $Nodes
    if ($OnlySelected -and $Selected -and @($Selected).Count -gt 0) {
        $pool = @($Nodes | Where-Object { $Selected -contains $_.tag })
    }

    foreach ($n in $pool) {
        $o = [ordered]@{ type = $n.type; tag = $n.tag; server = $n.server; server_port = $n.server_port }
        foreach ($k in @('uuid', 'password', 'method', 'alter_id', 'flow', 'plugin', 'plugin_opts', 'congestion_control', 'tls', 'transport', 'obfs')) {
            if ($n.Contains($k) -and $null -ne $n[$k]) { $o[$k] = $n[$k] }
        }
        [void]$out.Add($o)
        [void]$tags.Add($n.tag)
    }

    # direct для процесса самого sing-box и служебных адресов
    [void]$out.Add([ordered]@{ type = 'direct'; tag = 'direct' })

    # группа выбора
    $useTags = @()
    if ($Selected -and @($Selected).Count -gt 0) { $useTags = @($Selected) } else { $useTags = @($tags) }
    if ($useTags.Count -gt 1) {
        [void]$out.Add([ordered]@{
            type = 'urltest'
            tag = 'proxy-group'
            outbounds = $useTags
            url = $TestUrl
            interval = '10m'
            tolerance = 50
            interrupt_exist_connections = $true
        })
    } elseif ($useTags.Count -eq 1) {
        [void]$out.Add([ordered]@{ type = 'selector'; tag = 'proxy-group'; outbounds = @($useTags[0]); default = $useTags[0]; interrupt_exist_connections = $true })
    } else {
        throw 'Нет ни одного сервера'
    }
    $final = 'proxy-group'

    # маршрутизация
    $rules = New-Object System.Collections.ArrayList
    [void]$rules.Add([ordered]@{ action = 'sniff' })
    [void]$rules.Add([ordered]@{ protocol = 'dns'; action = 'hijack-dns' })

    # per-app: перечисленные приложения идут НАПРЯМУЮ (важно для игр/античита)
    $directApps = @(($GameSafeProcesses + $AppList) | Where-Object { $_ } | Select-Object -Unique)
    if ($Mode -eq 'tun' -and $directApps.Count -gt 0) {
        [void]$rules.Add([ordered]@{
            process_name = $directApps
            outbound = 'direct'
        })
        Write-VpnLog ("  direct-exclude apps: " + ($directApps -join ', '))
    }

    # локальные сети идём напрямую (в TUN это обязательно)
    [void]$rules.Add([ordered]@{
        ip_cidr = @('127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '224.0.0.0/4', 'fe80::/10', 'fc00::/7')
        outbound = 'direct'
    })

    $inbounds = New-Object System.Collections.ArrayList
    if ($Mode -eq 'tun') {
        [void]$inbounds.Add([ordered]@{
            type = 'tun'
            tag = 'tun-in'
            interface_name = 'vpn-launcher-tun'
            address = @('172.19.0.1/30', 'fdfe:dcba:9876::1/126')
            mtu = 1500
            auto_route = $true
            strict_route = $true
            stack = 'mixed'
        })
    } else {
        [void]$inbounds.Add([ordered]@{ type = 'socks'; tag = 'socks-in'; listen = '127.0.0.1'; listen_port = $script:SocksPort })
        [void]$inbounds.Add([ordered]@{ type = 'http'; tag = 'http-in'; listen = '127.0.0.1'; listen_port = ($script:SocksPort + 1) })
    }

    $cfg = [ordered]@{
        log = [ordered]@{ level = 'info'; timestamp = $true }
        dns = [ordered]@{
            servers = @(
                [ordered]@{ tag = 'dns-local'; type = 'local' },
                [ordered]@{ tag = 'dns-out'; type = 'udp'; server = '1.1.1.1'; server_port = 53 }
            )
            final = 'dns-out'
        }
        inbounds = @($inbounds)
        outbounds = @($out)
        route = [ordered]@{
            rules = @($rules)
            auto_detect_interface = $true
            default_domain_resolver = [ordered]@{ server = 'dns-local' }
            final = $final
        }
        experimental = [ordered]@{
            cache_file = [ordered]@{ enabled = $true; path = (Join-Path $script:InstallRoot 'cache.db') }
        }
    }

    $json = $cfg | ConvertTo-Json -Depth 30
    [IO.File]::WriteAllText($script:ConfigFile, $json, (New-Object System.Text.UTF8Encoding($false)))
    Write-VpnLog "config written: $($out.Count) outbounds, mode=$Mode, final=$final"
    return $script:ConfigFile
}

# Замер задержки до сервера: TCP-connect (ICMP до VPN-хостов обычно режется).
# Возвращает мс (лучший из попыток) или -1, если порт не отвечает.
function Measure-NodeLatency {
    param(
        [Parameter(Mandatory)] $Node,
        [int]$TimeoutMs = 2500,
        [int]$Attempts = 2
    )
    $srv = $Node['server']
    $prt = [int]$Node['server_port']
    $best = -1
    for ($a = 0; $a -lt $Attempts; $a++) {
        $c = New-Object System.Net.Sockets.TcpClient
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $okConn = $false
        try {
            $iar = $c.BeginConnect($srv, $prt, $null, $null)
            if ($iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
                $c.EndConnect($iar)
                $sw.Stop()
                $okConn = $true
                $ms = [int]$sw.ElapsedMilliseconds
                if ($best -lt 0 -or $ms -lt $best) { $best = $ms }
                if ($best -lt 60) { break }
            } else { break }
        } catch {
            break
        } finally {
            $sw.Stop()
            $c.Close()
        }
    }
    return $best
}

function Test-SingBoxConfig([string]$path) {
    $p = Start-Process -FilePath $script:SingBox -ArgumentList @('check', '-c', "`"$path`"") -NoNewWindow -Wait -PassThru -RedirectStandardOutput "$env:TEMP\sb_out.txt" -RedirectStandardError "$env:TEMP\sb_err.txt"
    $err = (@(Get-Content "$env:TEMP\sb_err.txt" -ErrorAction SilentlyContinue) -join [Environment]::NewLine)
    $err = ($err -replace "`e\[[0-9;]*m", '').Trim()
    if (-not $err) { $err = 'без вывода' }
    return @{ Ok = ($p.ExitCode -eq 0); Error = [string]$err }
}

# ---------------- состояние ----------------

function Get-VpnState {
    if (Test-Path $script:StateFile) {
        try { return (Get-Content $script:StateFile -Raw | ConvertFrom-Json) } catch { }
    }
    return [pscustomobject]@{
        subUrl = ''; mode = 'tun'; selected = ''; appList = @(); lastNodes = @(); autoUrlTest = $true
    }
}

function Save-VpnState($st) {
    $st | ConvertTo-Json -Depth 20 | Set-Content -Path $script:StateFile -Encoding UTF8
}
