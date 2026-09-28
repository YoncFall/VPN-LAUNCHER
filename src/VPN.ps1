# VPN.ps1 - графический клиент. Движок sing-box (SagerNet).
# Запуск:  VPNLauncher.exe (своё окно и своя иконка, без консоли)

param([switch]$Autoconnect)

. (Join-Path $PSScriptRoot 'core.ps1')

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
. (Join-Path $PSScriptRoot 'theme.ps1')

# Ошибки в обработчиках не должны вешать окно модальным диалогом - логируем и показываем в статусе
[System.Windows.Forms.Application]::SetUnhandledExceptionMode([System.Windows.Forms.UnhandledExceptionMode]::CatchException)
$script:ExHandler = [System.Threading.ThreadExceptionEventHandler] {
    param($sender, $e)
    Write-VpnLog ('UI ERROR: ' + $e.Exception.Message)
    try {
        $script:Status.Text = 'Внутренняя ошибка (см. лог)'
        $script:Status.ForeColor = [System.Drawing.Color]::Salmon
    } catch { }
}
[System.Windows.Forms.Application]::add_ThreadException($script:ExHandler)

$script:State = Get-VpnState
$script:Proc = $null
$script:Nodes = @()
$script:Busy = $false

$identGlobal = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmGlobal = (New-Object Security.Principal.WindowsPrincipal($identGlobal)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# ---------------- форма ----------------

$form = New-Object System.Windows.Forms.Form
$form.Text = 'VPN ЛАУНЧЕР BY @YoncFALL'
$form.ClientSize = New-Object System.Drawing.Size(620, 726)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'None'
$form.MaximizeBox = $false
$form.BackColor = $script:Pal.Bg
$form.ForeColor = $script:Pal.Text

# иконка приложения: окно, панель задач и Alt+Tab
try {
    $icoPath = Join-Path $PSScriptRoot 'app.ico'
    if (-not (Test-Path $icoPath)) { $icoPath = Join-Path (Join-Path $PSScriptRoot 'src') 'app.ico' }
    if (Test-Path $icoPath) { $form.Icon = [System.Drawing.Icon]::new($icoPath) }
} catch {
    Write-VpnLog ('icon error: ' + $_.Exception.Message)
}

# закруглённые углы + своя шапка вместо системного заголовка
Install-GameCorners $form
$script:Cap = Install-GameTitleBar $form 46
$form.Add_Paint({
    $g = $_.Graphics
    $gp0 = New-Object System.Drawing.Point -ArgumentList 0, 0
    $gp1 = New-Object System.Drawing.Point -ArgumentList 0, $form.ClientSize.Height
    $br = New-Object System.Drawing.Drawing2D.LinearGradientBrush -ArgumentList $gp0, $gp1, $script:Pal.Bg2, $script:Pal.Bg
    $rect = New-Object System.Drawing.Rectangle -ArgumentList 0, 0, $form.ClientSize.Width, $form.ClientSize.Height
    $g.FillRectangle($br, $rect)
    $br.Dispose()
})

function Add-Label($t, $x, $y, $w) {
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $t
    $l.Location = New-Object System.Drawing.Point($x, $y)
    $l.Size = New-Object System.Drawing.Size($w, 18)
    $l.ForeColor = [System.Drawing.Color]::Gainsboro
    $form.Controls.Add($l)
    return $l
}
function Add-TextBox($x, $y, $w, $text) {
    $t = New-Object System.Windows.Forms.TextBox
    $t.Location = New-Object System.Drawing.Point($x, $y)
    $t.Size = New-Object System.Drawing.Size($w, 26)
    $t.Text = $text
    $t.BackColor = [System.Drawing.Color]::FromArgb(45, 48, 54)
    $t.ForeColor = [System.Drawing.Color]::White
    $t.BorderStyle = 'FixedSingle'
    $form.Controls.Add($t)
    return $t
}
function Add-Button($t, $x, $y, $w, $h, $color) {
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $t
    $b.Location = New-Object System.Drawing.Point($x, $y)
    $b.Size = New-Object System.Drawing.Size($w, $h)
    $b.FlatStyle = 'Flat'
    $b.BackColor = $color
    $b.ForeColor = [System.Drawing.Color]::White
    $form.Controls.Add($b)
    return $b
}

function Format-NodeRow($n) {
    $fl = switch ($n['proto']) {
        'vless' { 'VLESS' } 'vmess' { 'VMESS' } 'trojan' { 'TROJAN' }
        'shadowsocks' { 'SS' } 'hysteria2' { 'HY2' } 'tuic' { 'TUIC' } default { '???' }
    }
    # колонку пинга рисует сам список, поэтому в тексте её нет
    return ('{0,-6} {1}' -f $fl, $n['display'])
}

New-GameCaption 'ПОДПИСКА' 16 62 300 | ForEach-Object { $form.Controls.Add($_) }
$txtSub = New-GameTextBox 16 80 588 30 $script:State.subUrl
$form.Controls.Add($txtSub)

$btnLoad = New-GameButton 'Загрузить подписку' 16 118 200 36 'ghost'
$form.Controls.Add($btnLoad)
$btnLoad.Add_Click({
    if ($script:Busy) { return }
    $url = $script:UrlBox.Text.Trim()
    if (-not $url) {
        [System.Windows.Forms.MessageBox]::Show('Вставь ссылку на подписку.') | Out-Null
        return
    }
    $script:Busy = $true
    Set-BtnText $script:LoadBtn 'Загрузка...'
    $script:LoadBtn.Enabled = $false
    [System.Windows.Forms.Application]::DoEvents()
    try {
        $script:Nodes = @(Get-SubscriptionNodes $url)
        $script:State.subUrl = $url
        Save-VpnState $script:State
        $script:Ping = @{}
        $script:List.BeginUpdate()
        $script:List.Items.Clear()
        foreach ($n in $script:Nodes) {
            [void]$script:List.Items.Add((Format-NodeRow $n))
        }
        $script:List.EndUpdate()
        $script:Status.Text = ('Серверов загружено: {0}' -f $script:Nodes.Count)
        $script:Status.ForeColor = [System.Drawing.Color]::LightGreen
    } catch {
        $script:Status.Text = 'Ошибка загрузки'
        $script:Status.ForeColor = [System.Drawing.Color]::Salmon
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'VPN ЛАУНЧЕР BY @YoncFALL', 'OK', 'Error') | Out-Null
    } finally {
$script:Busy = $false
$script:Ping = @{}
$script:PingJob = $null
$script:PingHandle = $null
        Set-BtnText $script:LoadBtn 'Загрузить подписку'
        $script:LoadBtn.Enabled = $true
    }
})

$btnPing = New-GameButton 'Проверить пинг' 224 118 160 36 'ghost'
$form.Controls.Add($btnPing)
$btnLog = New-GameButton 'Открыть лог' 392 118 212 36 'ghost'
$form.Controls.Add($btnLog)
$btnLog.Add_Click({ if (Test-Path $script:LogFile) { Start-Process notepad $script:LogFile } })

New-GameCaption 'СЕРВЕРЫ' 16 170 200 | ForEach-Object { $form.Controls.Add($_) }
$hint = Add-Label 'Ctrl+клик - выбрать несколько, пусто - авто-тест всех' 216 170 388
$hint.ForeColor = $script:Pal.TextDim
$hint.Font = $script:FSub
$hint.TextAlign = 'MiddleRight'
$lstServers = New-GameList 16 188 588 196 $true
$form.Controls.Add($lstServers)

New-GameCaption 'РЕЖИМ' 16 396 200 | ForEach-Object { $form.Controls.Add($_) }

$rbTun = New-GameRadio 'Весь трафик - TUN (нужен админ)' 16 414 288 38
$rbTun.Checked = ($script:State.mode -ne 'proxy')
$form.Controls.Add($rbTun)

$rbProxy = New-GameRadio 'Системный прокси' 312 414 292 38
$rbProxy.Checked = ($script:State.mode -eq 'proxy')
$form.Controls.Add($rbProxy)

New-GameCaption 'ИСКЛЮЧЕНИЯ ИЗ ТУННЕЛЯ' 16 466 320 | ForEach-Object { $form.Controls.Add($_) }
$hint2 = Add-Label 'игры, Steam и античиты исключены автоматически' 336 466 268
$hint2.ForeColor = $script:Pal.TextDim
$hint2.Font = $script:FSub
$hint2.TextAlign = 'MiddleRight'

$lstExcl = New-GameList 16 486 300 92 $false
$form.Controls.Add($lstExcl)

$cmbProc = New-GameCombo 324 486 280 30
$form.Controls.Add($cmbProc)

$btnExclAdd = New-GameButton 'Добавить' 324 522 280 30 'ghost'
$btnExclDel = New-GameButton 'Удалить' 324 558 136 30 'ghost'
$btnExclClr = New-GameButton 'Очистить' 468 558 136 30 'ghost'
$form.Controls.Add($btnExclAdd)
$form.Controls.Add($btnExclDel)
$form.Controls.Add($btnExclClr)

$hint3 = Add-Label 'Список процессов обновляется при запуске. В поле можно вписать имя .exe вручную.' 16 590 588
$hint3.ForeColor = $script:Pal.TextDim
$hint3.Font = $script:FSub

$btnConnect = New-GameButton 'ПОДКЛЮЧИТЬСЯ' 16 614 300 46 'accent'
$btnDisconnect = New-GameButton 'ОТКЛЮЧИТЬ' 324 614 140 46 'danger'
$btnDisconnect.Enabled = $false
$btnTestCfg = New-GameButton 'Проверить конфиг' 472 614 132 46 'ghost'
$form.Controls.Add($btnConnect)
$form.Controls.Add($btnDisconnect)
$form.Controls.Add($btnTestCfg)

$ledStatus = New-GameLed 18 678 10
$script:StatusLed = $ledStatus
$form.Controls.Add($ledStatus)
$lblStatus = Add-Label 'Готов' 36 672 568 20
$lblStatus.ForeColor = [System.Drawing.Color]::Gainsboro
$lblStatus.Font = $script:FBody
$lblEgress = Add-Label '' 36 696 568 20
$lblEgress.ForeColor = [System.Drawing.Color]::DarkGray
$lblEgress.Font = $script:FMono

# ---------------- работа со списком исключений ----------------

function Save-ExclList {
    $items = @()
    foreach ($i in $lstExcl.Items) { $items += [string]$i }
    $script:State.appList = $items
    Save-VpnState $script:State
}

function Get-RunningExeList {
    $seen = New-Object System.Collections.ArrayList
    foreach ($p in (Get-Process -ErrorAction SilentlyContinue)) {
        $n = $null
        try { $n = $p.ProcessName } catch { continue }
        if (-not $n) { continue }
        $exe = "$n.exe"
        if ($exe -notin $seen) { [void]$seen.Add($exe) }
    }
    return @($seen | Sort-Object)
}

function Fill-ProcCombo {
    $cur = $cmbProc.Text
    $cmbProc.Items.Clear()
    foreach ($e in (Get-RunningExeList)) { [void]$cmbProc.Items.Add($e) }
    if ($cur) { $cmbProc.Text = $cur }
}

function Add-Excl {
    $v = $cmbProc.Text.Trim()
    if (-not $v) { return }
    if ($v -notmatch '\.exe$') { $v = "$v.exe" }
    if ($v -notmatch '^[\w\-. ]+\.exe$') {
        $script:Status.Text = 'Не похоже на имя процесса (.exe)'
        $script:Status.ForeColor = [System.Drawing.Color]::Salmon
        return
    }
    if ($lstExcl.Items.Contains($v)) {
        $script:Status.Text = "$v уже есть в списке"
        $script:Status.ForeColor = [System.Drawing.Color]::Khaki
        return
    }
    if ($GameSafeProcesses -contains $v) {
        $script:Status.Text = "$v и так исключён автоматически"
        $script:Status.ForeColor = [System.Drawing.Color]::Khaki
        return
    }
    [void]$lstExcl.Items.Add($v)
    $cmbProc.Text = ''
    Save-ExclList
    $script:Status.Text = "Добавлено исключение: $v"
    $script:Status.ForeColor = [System.Drawing.Color]::LightGreen
    Write-VpnLog "exclusion added by user: $v"
}

$btnExclAdd.Add_Click({ Add-Excl })
$cmbProc.Add_KeyDown({
    if ($_.KeyCode -eq [System.Windows.Forms.Keys]::Enter) {
        Add-Excl
        $_.SuppressKeyPress = $true
    }
})
$btnExclDel.Add_Click({
    $sel = @($lstExcl.SelectedItems)
    foreach ($s in $sel) { [void]$lstExcl.Items.Remove($s) }
    if ($sel.Count) { Save-ExclList }
})
$btnExclClr.Add_Click({
    if ($lstExcl.Items.Count -eq 0) { return }
    $lstExcl.Items.Clear()
    Save-ExclList
    $script:Status.Text = 'Список исключений очищен'
    $script:Status.ForeColor = [System.Drawing.Color]::Khaki
})
$lstExcl.Add_DoubleClick({ $btnExclDel.PerformClick() })

foreach ($a in @($script:State.appList)) {
    if ($a) { [void]$lstExcl.Items.Add([string]$a) }
}
Fill-ProcCombo

# ссылки на элементы для обработчиков
$script:UrlBox = $txtSub
$script:List = $lstServers
$script:Status = $lblStatus
$script:Egress = $lblEgress
$script:LoadBtn = $btnLoad
$script:PingBtn = $btnPing

function Get-SelectedTags {
    $res = @()
    foreach ($ix in $lstServers.SelectedIndices) {
        if ($ix -ge 0 -and $ix -lt $script:Nodes.Count) { $res += $script:Nodes[$ix].tag }
    }
    return $res
}
function Get-AppList {
    $res = @()
    foreach ($i in $lstExcl.Items) {
        $a = ([string]$i).Trim()
        if ($a) { $res += $a }
    }
    return $res
}

# ---------------- проверка пинга по всем серверам ----------------

$script:PingResults = New-Object System.Collections.Concurrent.ConcurrentQueue[object]
$script:PingDone = 0
$script:PingTotal = 0

$script:PingTick = New-Object System.Windows.Forms.Timer
$script:PingTick.Interval = 200
$script:PingTick.Add_Tick({
    try {
        $dirty = $false
        $out = $null
        while ($script:PingResults.TryDequeue([ref]$out)) {
            $script:Ping[$out.tag] = $out.ms
            $script:PingDone++
            $ix = -1
            for ($i = 0; $i -lt $script:Nodes.Count; $i++) {
                if ($script:Nodes[$i]['tag'] -eq $out.tag) { $ix = $i; break }
            }
            if ($ix -ge 0) { $lstServers.Items[$ix] = Format-NodeRow $script:Nodes[$ix]; $dirty = $true }
        }
        if ($dirty) { $lstServers.Refresh() }
        $script:Status.Text = ('Проверка пинга: {0} из {1}' -f $script:PingDone, $script:PingTotal)
        $script:Status.ForeColor = [System.Drawing.Color]::Khaki

        if ($script:PingHandle -and $script:PingHandle.IsCompleted) {
            $script:PingTick.Stop()
            $script:PingJob = $null
            $script:PingHandle = $null
            $script:PingBtn.Enabled = $true
            Set-BtnText $script:PingBtn 'Проверить пинг'
            $ok = @($script:Ping.Values | Where-Object { $_ -ge 0 }).Count
            $best = ($script:Ping.Values | Where-Object { $_ -ge 0 } | Measure-Object -Minimum).Minimum
            $script:Status.Text = ('Пинг готов: {0} из {1} доступны{2}' -f $ok, $script:Nodes.Count, $(if ($null -ne $best) { ", лучший {0} мс" -f $best } else { '' }))
            $script:Status.ForeColor = if ($ok -gt 0) { [System.Drawing.Color]::LightGreen } else { [System.Drawing.Color]::Salmon }
            Write-VpnLog ("ping done: $ok of $($script:Nodes.Count) reachable, best=$best ms")
            $lstServers.Refresh()
        }
    } catch {
        $script:PingTick.Stop()
        $script:PingJob = $null
        $script:PingHandle = $null
        $script:PingBtn.Enabled = $true
        Set-BtnText $script:PingBtn 'Проверить пинг'
        $script:Status.Text = 'Ошибка проверки пинга (см. лог)'
        $script:Status.ForeColor = [System.Drawing.Color]::Salmon
        Write-VpnLog ("ping ERROR: " + $_.Exception.Message)
    }
})

$btnPing.Add_Click({
    try {
    if ($script:PingJob) { return }
    if ($script:Nodes.Count -eq 0) {
        [System.Windows.Forms.MessageBox]::Show('Сначала загрузи подписку.') | Out-Null
        return
    }
    $targets = @()
    for ($i = 0; $i -lt $script:Nodes.Count; $i++) {
        $n = $script:Nodes[$i]
        $targets += @{ tag = $n['tag']; server = $n['server']; server_port = $n['server_port'] }
        $script:Ping[$n['tag']] = -2
        $lstServers.Items[$i] = Format-NodeRow $n
    }
    $lstServers.Refresh()

    $script:PingResults = New-Object System.Collections.Concurrent.ConcurrentQueue[object]
    $script:PingDone = 0
    $script:PingTotal = $targets.Count
    $script:PingBtn.Enabled = $false
    Set-BtnText $script:PingBtn 'Пинг...'

    $ps = [PowerShell]::Create()
    $ps.AddScript({
        param($list, $queue)
        foreach ($t in $list) {
            $best = -1
            for ($a = 0; $a -lt 2; $a++) {
                $c = New-Object System.Net.Sockets.TcpClient
                $sw = [System.Diagnostics.Stopwatch]::StartNew()
                try {
                    $iar = $c.BeginConnect($t.server, [int]$t.server_port, $null, $null)
                    if ($iar.AsyncWaitHandle.WaitOne(2500, $false)) {
                        $c.EndConnect($iar)
                        $sw.Stop()
                        $ms = [int]$sw.ElapsedMilliseconds
                        if ($best -lt 0 -or $ms -lt $best) { $best = $ms }
                        if ($best -lt 60) { break }
                    } else { break }
                } catch { break } finally { $sw.Stop(); $c.Close() }
            }
            $queue.Enqueue([pscustomobject]@{ tag = $t.tag; ms = $best })
        }
    }).AddArgument($targets).AddArgument($script:PingResults) | Out-Null
    $script:PingJob = $ps
    $script:PingHandle = $ps.BeginInvoke()
    $script:PingTick.Start()
    } catch {
        $script:PingTick.Stop()
        $script:PingJob = $null
        $script:PingHandle = $null
        $script:PingBtn.Enabled = $true
        Set-BtnText $script:PingBtn 'Проверить пинг'
        $script:Status.Text = 'Ошибка проверки пинга (см. лог)'
        $script:Status.ForeColor = [System.Drawing.Color]::Salmon
        Write-VpnLog ('ping click ERROR: ' + $_.Exception.Message)
    }
})

# ---------------- системный прокси ----------------

function Set-ProxyOn {
    $is = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
    Set-ItemProperty $is -Name ProxyEnable -Value 1
    Set-ItemProperty $is -Name ProxyServer -Value ("socks=127.0.0.1:{0};http=127.0.0.1:{1}" -f $script:SocksPort, ($script:SocksPort + 1))
    Set-ItemProperty $is -Name ProxyOverride -Value 'localhost;127.*;10.*;172.16.*;192.168.*;<local>'
    Write-VpnLog "system proxy ON 127.0.0.1:$script:SocksPort"
}
function Set-ProxyOff {
    $is = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
    if ((Get-ItemProperty $is -ErrorAction SilentlyContinue).ProxyEnable -eq 1) {
        Set-ItemProperty $is -Name ProxyEnable -Value 0
        Set-ItemProperty $is -Name ProxyServer -Value ''
        Write-VpnLog 'system proxy OFF'
    }
}

# ---------------- подключение ----------------

$btnConnect.Add_Click({
    if ($script:Nodes.Count -eq 0) {
        [System.Windows.Forms.MessageBox]::Show('Сначала загрузи подписку.') | Out-Null
        return
    }
    $mode = 'proxy'
    if ($rbTun.Checked) { $mode = 'tun' }
    $sel = Get-SelectedTags
    $apps = Get-AppList

    $script:State.mode = $mode
    $script:State.appList = $apps
    $script:State.subUrl = $txtSub.Text.Trim()
    if ($sel.Count -gt 0) { $script:State.selected = ($sel -join ',') } else { $script:State.selected = '' }
    Save-VpnState $script:State

    # TUN требует администратора
    $ident = [Security.Principal.WindowsIdentity]::GetCurrent()
    $isAdm = (New-Object Security.Principal.WindowsPrincipal($ident)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($mode -eq 'tun' -and -not $isAdm) {
        $lblStatus.Text = 'Нужны права администратора...'
        $lblStatus.ForeColor = [System.Drawing.Color]::Khaki
        $btnConnect.Enabled = $false
        [System.Windows.Forms.Application]::DoEvents()
        $ans = [System.Windows.Forms.MessageBox]::Show(
            'Режим "Весь трафик (TUN)" работает только с правами администратора.' + "`r`n`r`n" +
            'Сейчас приложение перезапустится с повышенными правами и подключится само.' + "`r`n" +
            'В окне Windows нажмите "Да".',
            'VPN ЛАУНЧЕР BY @YoncFALL', 'OKCancel', 'Information')
        if ($ans -ne 'OK') {
            Write-VpnLog 'elevation cancelled by user'
            $lblStatus.Text = 'Отменено - подключение не выполнено'
            $lblStatus.ForeColor = [System.Drawing.Color]::Salmon
            $btnConnect.Enabled = $true
            return
        }
        try {
            # Повышаем права собственной программы, а не powershell.exe.
            # Запуск "powershell -Verb RunAs -ExecutionPolicy Bypass" - это
            # ровно то, на что antivirus и SmartScreen реагируют предупреждением,
            # плюс в панели задач появлялся чужой значок.
            $hostExe = $null
            foreach ($cand in @((Join-Path $PSScriptRoot 'VPNLauncher.exe'),
                                (Join-Path (Split-Path -Parent $PSScriptRoot) 'bin\VPNLauncher.exe'))) {
                if ($cand -and (Test-Path -LiteralPath $cand)) { $hostExe = $cand; break }
            }
            if ($hostExe) {
                Write-VpnLog ('elevating own executable: ' + $hostExe)
                Start-Process -FilePath $hostExe -Verb RunAs -ArgumentList '--autoconnect' | Out-Null
            } else {
                # запасной путь для запуска из исходников без собранного exe
                Write-VpnLog 'VPNLauncher.exe not found, falling back to powershell host'
                Start-Process powershell -Verb RunAs -ArgumentList @('-NoProfile', '-STA', '-File', "`"$PSCommandPath`"", '-Autoconnect')
            }
        } catch {
            Write-VpnLog ('elevation ERROR: ' + $_.Exception.Message)
            $lblStatus.Text = 'Не удалось получить права администратора'
            $lblStatus.ForeColor = [System.Drawing.Color]::Salmon
            $btnConnect.Enabled = $true
            return
        }
        $lblStatus.Text = 'Запуск с правами администратора...'
        [System.Windows.Forms.Application]::DoEvents()
        $form.Close()
        return
    }

    $btnConnect.Enabled = $false
    $lblStatus.Text = 'Генерация конфига...'
    [System.Windows.Forms.Application]::DoEvents()
    try {
        $cfgPath = New-SingBoxConfig -Nodes $script:Nodes -Selected $sel -Mode $mode -AppList $apps
        $chk = Test-SingBoxConfig $cfgPath
        if (-not $chk.Ok) {
            Write-VpnLog ('config check failed: ' + $chk.Error)
            if ($sel.Count -gt 0) {
                Write-VpnLog 'retry with selected server only'
                $cfgPath = New-SingBoxConfig -Nodes $script:Nodes -Selected $sel -Mode $mode -AppList $apps -OnlySelected
                $chk = Test-SingBoxConfig $cfgPath
                if (-not $chk.Ok) { throw ('Конфиг не прошёл проверку: ' + $chk.Error) }
            } else {
                throw ('Конфиг не прошёл проверку: ' + $chk.Error)
            }
        }

        $lblStatus.Text = 'Запуск sing-box...'
        [System.Windows.Forms.Application]::DoEvents()

        $sbOut = Join-Path $PSScriptRoot 'singbox.log'
        foreach ($lf in @($sbOut, "$sbOut.err")) {
            if ((Get-Item $lf -ErrorAction SilentlyContinue).Length -gt 2MB) {
                Remove-Item $lf -Force -ErrorAction SilentlyContinue
            }
        }
        $script:Proc = Start-Process -FilePath $SingBox `
            -ArgumentList @('run', '-c', "`"$cfgPath`"", '-D', "`"$PSScriptRoot`"") `
            -WorkingDirectory $PSScriptRoot -WindowStyle Minimized -PassThru `
            -RedirectStandardOutput $sbOut -RedirectStandardError "$sbOut.err"

        Start-Sleep -Seconds 3
        if ($script:Proc.HasExited) {
            $e = Get-Content "$sbOut.err" -Raw -ErrorAction SilentlyContinue
            throw ('sing-box завершился: ' + $e)
        }
        if ($mode -eq 'proxy') { Set-ProxyOn }

        $btnDisconnect.Enabled = $true
        $lblStatus.Text = 'ПОДКЛЮЧЕНО  |  pid ' + $script:Proc.Id + '  |  ' + $(if ($sel.Count) { "$($sel.Count) сервер(а)" } else { 'авто-тест всех' })
        $lblStatus.ForeColor = [System.Drawing.Color]::LightGreen
        $script:Tick.Start()
    } catch {
        Write-VpnLog ('connect ERROR: ' + $_.Exception.Message)
        $lblStatus.Text = 'Не удалось подключиться'
        $lblStatus.ForeColor = [System.Drawing.Color]::Salmon
        $btnConnect.Enabled = $true
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Ошибка подключения', 'OK', 'Error') | Out-Null
    }
})

$btnDisconnect.Add_Click({
    if ($script:Proc -and -not $script:Proc.HasExited) {
        try { Stop-Process -Id $script:Proc.Id -Force } catch { }
    }
    $script:Proc = $null
    Set-ProxyOff
    $script:Tick.Stop()
    $btnConnect.Enabled = $true
    $btnDisconnect.Enabled = $false
    $lblStatus.Text = 'Отключено'
    $lblStatus.ForeColor = [System.Drawing.Color]::Gainsboro
    $lblEgress.Text = ''
})

$btnTestCfg.Add_Click({
    if ($script:Nodes.Count -eq 0) {
        [System.Windows.Forms.MessageBox]::Show('Сначала загрузи подписку.') | Out-Null
        return
    }
    $mode = 'proxy'
    if ($rbTun.Checked) { $mode = 'tun' }
    try {
        $cfg = New-SingBoxConfig -Nodes $script:Nodes -Selected (Get-SelectedTags) -Mode $mode -AppList (Get-AppList)
        $chk = Test-SingBoxConfig $cfg
        if ($chk.Ok) {
            $lblStatus.Text = 'Конфиг корректен'
            $lblStatus.ForeColor = [System.Drawing.Color]::LightGreen
            [System.Windows.Forms.MessageBox]::Show('Конфиг корректен.', 'VPN ЛАУНЧЕР BY @YoncFALL', 'OK', 'Information') | Out-Null
        } else {
            [System.Windows.Forms.MessageBox]::Show($chk.Error, 'Ошибка конфига', 'OK', 'Error') | Out-Null
        }
    } catch {
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Ошибка', 'OK', 'Error') | Out-Null
    }
})

# ---------------- таймер ----------------

$script:Tick = New-Object System.Windows.Forms.Timer
$script:Tick.Interval = 10000
$script:Counter = 0
$script:Tick.Add_Tick({
    $script:Counter++
    if ($script:Proc -and $script:Proc.HasExited) {
        $script:Tick.Stop()
        Set-ProxyOff
        $script:Proc = $null
        $btnConnect.Enabled = $true
        $btnDisconnect.Enabled = $false
        $lblStatus.Text = 'Соединение оборвалось - sing-box завершился, смотри лог'
        $lblStatus.ForeColor = [System.Drawing.Color]::Salmon
        return
    }
    if (($script:Counter % 3) -eq 1) {
        try {
            $r = Invoke-WebRequest 'https://api.ipify.org?format=json' -UseBasicParsing -TimeoutSec 8
            $ip = ($r.Content | ConvertFrom-Json).ip
            $lblEgress.Text = "Внешний IP: $ip"
            $lblEgress.ForeColor = [System.Drawing.Color]::LightSteelBlue
        } catch {
            $lblEgress.Text = 'Внешний IP недоступен'
            $lblEgress.ForeColor = [System.Drawing.Color]::Gray
        }
    }
})

$form.Add_FormClosing({
    if ($script:PingJob) {
        try { [void]$script:PingJob.BeginStop($null, $null) } catch { }
    }
    if ($script:Proc -and -not $script:Proc.HasExited) {
        try { Stop-Process -Id $script:Proc.Id -Force } catch { }
    }
    Set-ProxyOff
})

if ($isAdmGlobal) { $form.Text = 'VPN ЛАУНЧЕР BY @YoncFALL (администратор)' }

if ($Autoconnect) {
    $script:AutoTimer = New-Object System.Windows.Forms.Timer
    $script:AutoTimer.Interval = 700
    $script:AutoTimer.Add_Tick({
        $script:AutoTimer.Stop()
        $lblStatus.Text = 'Загружаю подписку и подключаюсь...'
        $lblStatus.ForeColor = [System.Drawing.Color]::Khaki
        [System.Windows.Forms.Application]::DoEvents()

        $btnLoad.PerformClick()
        [System.Windows.Forms.Application]::DoEvents()
        if ($script:Nodes.Count -eq 0) {
            $lblStatus.Text = 'Не удалось загрузить подписку - проверь ссылку'
            $lblStatus.ForeColor = [System.Drawing.Color]::Salmon
            return
        }

        $rbTun.Checked = $true
        $rbProxy.Checked = $false

        $want = @($script:State.selected -split ',' | Where-Object { $_ })
        for ($i = 0; $i -lt $script:Nodes.Count; $i++) {
            if ($want -contains $script:Nodes[$i]['tag']) {
                $lstServers.SelectedIndices.Clear()
                [void]$lstServers.SelectedIndices.Add($i)
                break
            }
        }
        [System.Windows.Forms.Application]::DoEvents()
        $btnConnect.PerformClick()
    })
    $script:AutoTimer.Start()
}

Write-VpnLog 'GUI started'
[void]$form.ShowDialog()
