# VPN.ps1 - графический клиент. Движок sing-box (SagerNet).
# Запуск:  VPNLauncher.exe (своё окно и своя иконка, без консоли)

param([switch]$Autoconnect)

# core.ps1 и theme.ps1 лежат либо рядом со скриптом (раскладка установщика),
# либо в src\ (раскладка zip-архива и install.bat) - ищем оба места.
# Грузим их ТЕКСТОМ в память, а не dot-source'ом файла: dot-source файла
# зависит от политики выполнения сценариев, а на чистой Windows она
# Restricted, и ранее запуск падал с ошибкой "выполнение сценариев отключено".
function Read-VpnScriptText([string]$name) {
    $p = Join-Path $PSScriptRoot $name
    if (-not (Test-Path $p)) { $p = Join-Path (Join-Path $PSScriptRoot 'src') $name }
    if (-not (Test-Path $p)) { throw "Не найден $name рядом с программой или в src\" }
    $txt = [IO.File]::ReadAllText($p, [Text.Encoding]::UTF8)
    # у скрипта, загруженного текстом, $PSScriptRoot не определён -
    # подставляем свой, как это делает хост (VPNLauncher.exe).
    # Токен собираем из частей: хост тоже подменяет $PSScriptRoot текстом,
    # и попал бы внутрь этой строки-шаблона, сломав синтаксис.
    if ($PSScriptRoot) {
        $root = "'" + $PSScriptRoot.Replace("'", "''") + "'"
        $tkn = '$' + 'PSScriptRoot'
        $txt = $txt.Replace($tkn, $root)
    }
    return $txt
}

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

# важен порядок: сборки должны быть загружены до theme.ps1 - тот строит
# палитру [System.Drawing.Color] прямо при загрузке
$__core = Read-VpnScriptText 'core.ps1'
. ([scriptblock]::Create($__core))
Remove-Variable __core
$__theme = Read-VpnScriptText 'theme.ps1'
. ([scriptblock]::Create($__theme))
Remove-Variable __theme
Remove-Item Function:\Read-VpnScriptText -ErrorAction SilentlyContinue

# Ошибки в обработчиках не должны вешать окно модальным диалогом - логируем и показываем в статусе
[System.Windows.Forms.Application]::SetUnhandledExceptionMode([System.Windows.Forms.UnhandledExceptionMode]::CatchException)
$script:ExHandler = [System.Threading.ThreadExceptionEventHandler] {
    param($sender, $e)
    Write-VpnLog ('UI ERROR: ' + $e.Exception.Message)
    try {
        $script:Status.Text = 'Внутренняя ошибка (см. лог)'
        $script:Status.ForeColor = $script:Pal.Danger
    } catch { }
}
[System.Windows.Forms.Application]::add_ThreadException($script:ExHandler)

$script:State = Get-VpnState
$script:Proc = $null
$script:Nodes = @()
$script:Busy = $false
$script:Ping = @{}   # тема читает его при отрисовке списка, должно существовать с самого старта

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



function Format-NodeRow($n) {
    # протокол и пинг рисует сам список отдельными колонками,
    # в тексте строки остаётся только имя сервера
    return [string]$n['display']
}

# ---------------- карточка интерфейса ----------------
# Вся раскладка живёт на одной скруглённой карточке поверх градиентного фона.
$card = New-GameCard 14 54 592 664 14
$form.Controls.Add($card)

New-GameCaption 'ПОДПИСКА' 18 12 300 | ForEach-Object { $card.Controls.Add($_) }
$txtSub = New-GameField 18 30 556 30 $script:State.subUrl
$txtSub.Placeholder = 'вставь ссылку на подписку (https://...)'
$card.Controls.Add($txtSub)

$btnLoad = New-GameButton 'Загрузить подписку' 18 66 208 34 'ghost'
$btnPing = New-GameButton 'Проверить пинг' 232 66 150 34 'ghost'
$btnLog = New-GameButton 'Открыть лог' 388 66 168 34 'ghost'
foreach ($b in @($btnLoad, $btnPing, $btnLog)) { $card.Controls.Add($b) }

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
        $script:Status.ForeColor = $script:Pal.Accent2
    } catch {
        $script:Status.Text = 'Ошибка загрузки'
        $script:Status.ForeColor = $script:Pal.Danger
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

$btnLog.Add_Click({ if (Test-Path $script:LogFile) { Start-Process notepad $script:LogFile } })

$div1 = New-GameDivider 18 106 556
$card.Controls.Add($div1)

New-GameCaption 'СЕРВЕРЫ' 18 118 200 | ForEach-Object { $card.Controls.Add($_) }
New-GameLabel 'Ctrl+клик - несколько · пусто - авто-тест всех' 300 136 274 14 'TextDim' 'FSub' 'MiddleRight' | ForEach-Object { $card.Controls.Add($_) }
# шапка колонок совпадает с колонками, которые рисует список
New-GameLabel 'ПРОТОКОЛ' 18 136 57 14 'TextDim' 'FCaps' 'MiddleRight' | ForEach-Object { $card.Controls.Add($_) }
New-GameLabel 'СЕРВЕР' 81 136 300 14 'TextDim' 'FCaps' 'MiddleLeft' | ForEach-Object { $card.Controls.Add($_) }
New-GameLabel 'ПИНГ' 480 136 81 14 'TextDim' 'FCaps' 'MiddleRight' | ForEach-Object { $card.Controls.Add($_) }

$boxServers = New-GameListBox 18 152 556 178 $true
$lstServers = $boxServers.List
$card.Controls.Add($boxServers.Frame)

$div2 = New-GameDivider 18 340 556
$card.Controls.Add($div2)

New-GameCaption 'РЕЖИМ' 18 352 200 | ForEach-Object { $card.Controls.Add($_) }

$rbTun = New-GameRadio 'Весь трафик - TUN (нужен админ)' 18 368 270 36
$rbTun.Checked = ($script:State.mode -ne 'proxy')
$card.Controls.Add($rbTun)

$rbProxy = New-GameRadio 'Системный прокси' 294 368 262 36
$rbProxy.Checked = ($script:State.mode -eq 'proxy')
$card.Controls.Add($rbProxy)

$div3 = New-GameDivider 18 412 556
$card.Controls.Add($div3)

New-GameCaption 'ИСКЛЮЧЕНИЯ' 18 424 320 | ForEach-Object { $card.Controls.Add($_) }
New-GameLabel 'игры, Steam и античиты исключены автоматически' 300 424 274 16 'TextDim' 'FSub' 'MiddleRight' | ForEach-Object { $card.Controls.Add($_) }

$boxExcl = New-GameListBox 18 440 260 84 $false
$lstExcl = $boxExcl.List
$card.Controls.Add($boxExcl.Frame)

$cmbProc = New-GameCombo 288 440 286 30
$card.Controls.Add($cmbProc)

$btnExclAdd = New-GameButton 'Добавить' 288 474 286 30 'ghost'
$btnExclDel = New-GameButton 'Удалить' 288 508 138 30 'ghost'
$btnExclClr = New-GameButton 'Очистить' 426 508 130 30 'ghost'
foreach ($b in @($btnExclAdd, $btnExclDel, $btnExclClr)) { $card.Controls.Add($b) }

New-GameLabel 'Список процессов обновляется при запуске. В поле можно вписать имя .exe вручную.' 18 546 556 16 'TextDim' 'FSub' 'MiddleLeft' | ForEach-Object { $card.Controls.Add($_) }

$div4 = New-GameDivider 18 570 556
$card.Controls.Add($div4)

$btnConnect = New-GameButton 'ПОДКЛЮЧИТЬСЯ' 18 582 288 42 'accent' 9
$btnDisconnect = New-GameButton 'ОТКЛЮЧИТЬ' 316 582 118 42 'danger' 9
$btnDisconnect.Enabled = $false
$btnTestCfg = New-GameButton 'Проверить конфиг' 444 582 112 42 'ghost' 9
foreach ($b in @($btnConnect, $btnDisconnect, $btnTestCfg)) { $card.Controls.Add($b) }

$ledStatus = New-GameLed 18 640 10
$script:StatusLed = $ledStatus
$card.Controls.Add($ledStatus)
$lblStatus = New-GameLabel 'Готов' 36 634 250 18 'Text' 'FBody' 'MiddleLeft'
$card.Controls.Add($lblStatus)
$lblEgress = New-GameLabel '' 300 634 274 18 'TextDim' 'FMono' 'MiddleRight'
$card.Controls.Add($lblEgress)

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
        $script:Status.ForeColor = $script:Pal.Danger
        return
    }
    if ($lstExcl.Items.Contains($v)) {
        $script:Status.Text = "$v уже есть в списке"
        $script:Status.ForeColor = $script:Pal.Warn
        return
    }
    if ($GameSafeProcesses -contains $v) {
        $script:Status.Text = "$v и так исключён автоматически"
        $script:Status.ForeColor = $script:Pal.Warn
        return
    }
    [void]$lstExcl.Items.Add($v)
    $cmbProc.Text = ''
    Save-ExclList
    $script:Status.Text = "Добавлено исключение: $v"
    $script:Status.ForeColor = $script:Pal.Accent2
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
    $script:Status.ForeColor = $script:Pal.Warn
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
        $script:Status.ForeColor = $script:Pal.Warn

        if ($script:PingHandle -and $script:PingHandle.IsCompleted) {
            $script:PingTick.Stop()
            $script:PingJob = $null
            $script:PingHandle = $null
            $script:PingBtn.Enabled = $true
            Set-BtnText $script:PingBtn 'Проверить пинг'
            $ok = @($script:Ping.Values | Where-Object { $_ -ge 0 }).Count
            $best = ($script:Ping.Values | Where-Object { $_ -ge 0 } | Measure-Object -Minimum).Minimum
            $script:Status.Text = ('Пинг готов: {0} из {1} доступны{2}' -f $ok, $script:Nodes.Count, $(if ($null -ne $best) { ", лучший {0} мс" -f $best } else { '' }))
            $script:Status.ForeColor = if ($ok -gt 0) { $script:Pal.Accent2 } else { $script:Pal.Danger }
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
        $script:Status.ForeColor = $script:Pal.Danger
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
        $script:Status.ForeColor = $script:Pal.Danger
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
        $lblStatus.ForeColor = $script:Pal.Warn
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
            $lblStatus.ForeColor = $script:Pal.Danger
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
            $lblStatus.ForeColor = $script:Pal.Danger
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
        $lblStatus.ForeColor = $script:Pal.Accent2
        $script:Tick.Start()
    } catch {
        Write-VpnLog ('connect ERROR: ' + $_.Exception.Message)
        $lblStatus.Text = 'Не удалось подключиться'
        $lblStatus.ForeColor = $script:Pal.Danger
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
    $lblStatus.ForeColor = $script:Pal.Text
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
            $lblStatus.ForeColor = $script:Pal.Accent2
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
        $lblStatus.ForeColor = $script:Pal.Danger
        return
    }
    if (($script:Counter % 3) -eq 1) {
        try {
            $r = Invoke-WebRequest 'https://api.ipify.org?format=json' -UseBasicParsing -TimeoutSec 8
            $ip = ($r.Content | ConvertFrom-Json).ip
            $lblEgress.Text = "Внешний IP: $ip"
            $lblEgress.ForeColor = $script:Pal.Accent
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
        $lblStatus.ForeColor = $script:Pal.Warn
        [System.Windows.Forms.Application]::DoEvents()

        $btnLoad.PerformClick()
        [System.Windows.Forms.Application]::DoEvents()
        if ($script:Nodes.Count -eq 0) {
            $lblStatus.Text = 'Не удалось загрузить подписку - проверь ссылку'
            $lblStatus.ForeColor = $script:Pal.Danger
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
