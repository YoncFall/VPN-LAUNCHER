# theme.ps1 - оформление MyVPN: тёмная игровая тема.
# Подключается через dot-source из VPN.ps1. Логику VPN не меняет, только вид.

# P/Invoke объявляем один раз: повторный Add-Type с тем же именем падает
if (-not ('MyVpnNative' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class MyVpnNative {
    [DllImport("user32.dll")] public static extern bool ReleaseCapture();
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
}
'@
}

function Start-GameDrag {
    param($Form)
    try {
        [void][MyVpnNative]::ReleaseCapture()
        # 0xA1 = WM_NCLBUTTONDOWN, 0x2 = HTCAPTION - системная процедура перетаскивания окна
        [void][MyVpnNative]::SendMessage($Form.Handle, 0xA1, [IntPtr]0x2, [IntPtr]0)
    } catch {
        Write-VpnLog ('drag error: ' + $_.Exception.Message)
    }
}

$script:Pal = @{
    Bg      = [System.Drawing.Color]::FromArgb(12, 14, 19)
    Bg2     = [System.Drawing.Color]::FromArgb(18, 21, 29)
    Card    = [System.Drawing.Color]::FromArgb(24, 27, 37)
    CardHi  = [System.Drawing.Color]::FromArgb(33, 38, 51)
    Line    = [System.Drawing.Color]::FromArgb(46, 52, 68)
    Text    = [System.Drawing.Color]::FromArgb(230, 234, 242)
    TextDim = [System.Drawing.Color]::FromArgb(124, 134, 156)
    Accent  = [System.Drawing.Color]::FromArgb(0, 216, 255)
    Accent2 = [System.Drawing.Color]::FromArgb(0, 240, 168)
    Danger  = [System.Drawing.Color]::FromArgb(255, 77, 109)
    Warn    = [System.Drawing.Color]::FromArgb(255, 196, 84)
    Muted   = [System.Drawing.Color]::FromArgb(58, 64, 80)
}

function Get-GameFont {
    param([single]$Size, [System.Drawing.FontStyle]$Style = 'Regular', [string]$Family = '')
    if (-not $Family) {
        try { $probe = New-Object System.Drawing.Font('Bahnschrift', $Size, $Style); $Family = 'Bahnschrift'; $probe.Dispose() }
        catch { $Family = 'Segoe UI' }
    }
    return New-Object System.Drawing.Font($Family, $Size, $Style)
}

$script:FBody = Get-GameFont 9
$script:FHead = Get-GameFont 9.5 'Bold'
$script:FLogo = Get-GameFont 17 'Bold'
$script:FSub = Get-GameFont 7.5
$script:FBtn = Get-GameFont 8.5 'Bold'
$script:FCaps = Get-GameFont 7.5 'Bold'
$script:FMono = Get-GameFont 8.5
$script:FRow = Get-GameFont 9

function Get-RoundPath {
    param([int]$X, [int]$Y, [int]$W, [int]$H, [int]$R)
    $p = New-Object System.Drawing.Drawing2D.GraphicsPath
    if ($R -lt 1) { $p.AddRectangle((New-Object System.Drawing.Rectangle($X, $Y, $W, $H))); return $p }
    $d = $R * 2
    $d = [Math]::Min($d, [Math]::Min($W, $H))
    $p.AddArc($X, $Y, $d, $d, 180, 90)
    $p.AddArc($X + $W - $d, $Y, $d, $d, 270, 90)
    $p.AddArc($X + $W - $d, $Y + $H - $d, $d, $d, 0, 90)
    $p.AddArc($X, $Y + $H - $d, $d, $d, 90, 90)
    $p.CloseFigure()
    return $p
}

$script:BtnState = @{}

function Set-BtnText($b, [string]$t) {
    $b.Text = $t
    $b.Invalidate()
}

function Get-ButtonSkin {
    param([string]$Kind, [bool]$Hover, [bool]$Down, [bool]$Enabled)
    $pal = $script:Pal
    if (-not $Enabled) {
        return @{ Fill = [System.Drawing.Color]::FromArgb(22, 25, 33); Line = [System.Drawing.Color]::FromArgb(38, 43, 55); Text = [System.Drawing.Color]::FromArgb(72, 79, 96) }
    }
    switch ($Kind) {
        'accent' {
            $f = if ($Down) { [System.Drawing.Color]::FromArgb(0, 170, 205) } elseif ($Hover) { [System.Drawing.Color]::FromArgb(70, 235, 255) } else { $pal.Accent }
            return @{ Fill = $f; Line = $pal.Accent; Text = [System.Drawing.Color]::FromArgb(2, 26, 34) }
        }
        'ok' {
            $f = if ($Down) { [System.Drawing.Color]::FromArgb(0, 185, 130) } elseif ($Hover) { [System.Drawing.Color]::FromArgb(70, 255, 190) } else { $pal.Accent2 }
            return @{ Fill = $f; Line = $pal.Accent2; Text = [System.Drawing.Color]::FromArgb(2, 30, 20) }
        }
        'danger' {
            $f = if ($Down) { [System.Drawing.Color]::FromArgb(190, 50, 78) } elseif ($Hover) { [System.Drawing.Color]::FromArgb(255, 105, 133) } else { $pal.Danger }
            return @{ Fill = $f; Line = $pal.Danger; Text = [System.Drawing.Color]::FromArgb(38, 2, 10) }
        }
        default {
            $f = if ($Down) { [System.Drawing.Color]::FromArgb(24, 28, 38) } elseif ($Hover) { $pal.CardHi } else { $pal.Card }
            $ln = if ($Hover) { $pal.Accent } else { $pal.Line }
            $tx = if ($Hover) { $pal.Text } else { [System.Drawing.Color]::FromArgb(196, 203, 218) }
            return @{ Fill = $f; Line = $ln; Text = $tx }
        }
    }
}

function New-GameButton {
    param([string]$Text, [int]$X, [int]$Y, [int]$W, [int]$H, [string]$Kind = 'ghost')
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $Text
    $b.Tag = $Kind
    $b.Location = New-Object System.Drawing.Point($X, $Y)
    $b.Size = New-Object System.Drawing.Size($W, $H)
    $b.FlatStyle = 'Flat'
    $b.FlatAppearance.BorderSize = 0
    $b.FlatAppearance.MouseOverBackColor = $script:Pal.Card
    $b.FlatAppearance.MouseDownBackColor = $script:Pal.Card
    $b.BackColor = $script:Pal.Card
    $b.ForeColor = $script:Pal.Text
    $b.Cursor = [System.Windows.Forms.Cursors]::Hand
    $b.TabStop = $true

    $b.Add_Paint({
        param($s, $e)
        try {
            $g = $e.Graphics
            $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
            $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
            $r = New-Object System.Drawing.Rectangle(0, 0, $s.Width, $s.Height)
            $path = Get-RoundPath 1 1 ($s.Width - 2) ($s.Height - 2) 5
            $skin = Get-ButtonSkin ([string]$s.Tag) ([bool]$script:BtnState[$s.GetHashCode()].Hover) ([bool]$script:BtnState[$s.GetHashCode()].Down) $s.Enabled
            $br = New-Object System.Drawing.SolidBrush($skin.Fill)
            $g.FillPath($br, $path)
            $br.Dispose()
            if ($s.Enabled) {
                $pen = New-Object System.Drawing.Pen($skin.Line, 1)
                $g.DrawPath($pen, $path)
                $pen.Dispose()
            }
            $path.Dispose()
            $flags = [System.Windows.Forms.TextFormatFlags]::HorizontalCenter -bor
            [System.Windows.Forms.TextFormatFlags]::VerticalCenter -bor
            [System.Windows.Forms.TextFormatFlags]::EndEllipsis
            $inner = New-Object System.Drawing.Rectangle(6, 0, ($s.Width - 12), $s.Height)
            [System.Windows.Forms.TextRenderer]::DrawText($g, $s.Text, $script:FBtn, $inner, $skin.Text, $flags)
        } catch {
            Write-VpnLog ('btn paint error: ' + $_.Exception.Message)
        }
    })

    $b.Add_MouseEnter({
        $script:BtnState[$this.GetHashCode()] = @{ Hover = $true; Down = $false }
        $this.Invalidate()
    })
    $b.Add_MouseLeave({
        $script:BtnState[$this.GetHashCode()] = @{ Hover = $false; Down = $false }
        $this.Invalidate()
    })
    $b.Add_MouseDown({
        $script:BtnState[$this.GetHashCode()] = @{ Hover = $true; Down = $true }
        $this.Invalidate()
    })
    $b.Add_MouseUp({
        $script:BtnState[$this.GetHashCode()] = @{ Hover = $true; Down = $false }
        $this.Invalidate()
    })
    $b.Add_EnabledChanged({ $this.Invalidate() })
    $script:BtnState[$b.GetHashCode()] = @{ Hover = $false; Down = $false }
    return $b
}

function Set-GameListDraw {
    param($List, [bool]$Ping = $false, [int]$LeftPad = 8)
    $List.DrawMode = 'OwnerDrawFixed'
    $List.BorderStyle = 'None'
    $List.BackColor = $script:Pal.Card
    $List.ForeColor = $script:Pal.Text
    $List.Add_DrawItem({
        param($s, $e)
        if ($e.Index -lt 0 -or $e.Index -ge $s.Items.Count) { return }
        try {
            $g = $e.Graphics
            $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
            $pal = $script:Pal
            $sel = ($e.State -band [System.Windows.Forms.DrawItemState]::Selected) -ne 0

            $rowY = $e.Bounds.Y
            $rectRow = New-Object System.Drawing.Rectangle -ArgumentList $e.Bounds.X, $rowY, $e.Bounds.Width, $e.Bounds.Height
            $rectBar = New-Object System.Drawing.Rectangle -ArgumentList $e.Bounds.X, $rowY, 3, $e.Bounds.Height
            if ($sel) {
                $br = New-Object System.Drawing.SolidBrush -ArgumentList ([System.Drawing.Color]::FromArgb(38, 48, 64))
                $g.FillRectangle($br, $rectRow)
                $br.Dispose()
                $ac = New-Object System.Drawing.SolidBrush -ArgumentList $pal.Accent
                $g.FillRectangle($ac, $rectBar)
                $ac.Dispose()
            } elseif ($e.Index % 2 -eq 1) {
                $br = New-Object System.Drawing.SolidBrush -ArgumentList ([System.Drawing.Color]::FromArgb(20, 23, 31))
                $g.FillRectangle($br, $rectRow)
                $br.Dispose()
            }

            $text = [string]$s.Items[$e.Index]
            $clr = $pal.Text
            $font = $script:FRow
            $padL = $e.Bounds.X + $LeftPad
            $flags = [System.Windows.Forms.TextFormatFlags]::VerticalCenter -bor [System.Windows.Forms.TextFormatFlags]::EndEllipsis

            if ($Ping -and $e.Index -lt $script:Nodes.Count) {
                $tag = $script:Nodes[$e.Index]['tag']
                $ms = $null
                if ($tag -and $script:Ping.ContainsKey($tag)) { $ms = $script:Ping[$tag] }
                $rectName = New-Object System.Drawing.Rectangle -ArgumentList $padL, $rowY, ($e.Bounds.Width - 90), $e.Bounds.Height
                [System.Windows.Forms.TextRenderer]::DrawText($g, $text, $font, $rectName, $clr, $flags)
                $pingTxt = '---'
                $pclr = $pal.TextDim
                if ($null -ne $ms) {
                    if ($ms -eq -2) { $pingTxt = '...' }
                    elseif ($ms -lt 0) { $pingTxt = 'offline'; $pclr = $pal.Danger }
                    else {
                        $pingTxt = ('{0} ms' -f $ms)
                        if ($ms -lt 120) { $pclr = $pal.Accent2 }
                        elseif ($ms -lt 260) { $pclr = $pal.Warn }
                        else { $pclr = [System.Drawing.Color]::FromArgb(255, 140, 90) }
                    }
                }
                $psz = [System.Windows.Forms.TextRenderer]::MeasureText($pingTxt, $font)
                $px = $e.Bounds.X + $e.Bounds.Width - $psz.Width - 10
                $rectPing = New-Object System.Drawing.Rectangle -ArgumentList $px, $rowY, $psz.Width, $e.Bounds.Height
                [System.Windows.Forms.TextRenderer]::DrawText($g, $pingTxt, $font, $rectPing, $pclr, $flags)
            } else {
                $rect = New-Object System.Drawing.Rectangle -ArgumentList $padL, $rowY, ($e.Bounds.Width - $LeftPad - 8), $e.Bounds.Height
                [System.Windows.Forms.TextRenderer]::DrawText($g, $text, $font, $rect, $clr, $flags)
            }
        } catch {
            Write-VpnLog ('list draw error: ' + $_.Exception.Message)
        }
    })
}

function New-GameList {
    param([int]$X, [int]$Y, [int]$W, [int]$H, [bool]$Ping = $false)
    $l = New-Object System.Windows.Forms.ListBox
    $l.Location = New-Object System.Drawing.Point($X, $Y)
    $l.Size = New-Object System.Drawing.Size($W, $H)
    $l.MultiColumn = $false
    $l.HorizontalScrollbar = $true
    $l.IntegralHeight = $false
    $l.ItemHeight = 28
    $l.Font = $script:FBody
    Set-GameListDraw $l $Ping
    return $l
}

function New-GameCombo {
    param([int]$X, [int]$Y, [int]$W, [int]$H)
    $c = New-Object System.Windows.Forms.ComboBox
    $c.Location = New-Object System.Drawing.Point($X, $Y)
    $c.Size = New-Object System.Drawing.Size($W, $H)
    $c.DropDownStyle = 'DropDown'
    $c.DrawMode = 'OwnerDrawFixed'
    $c.BackColor = $script:Pal.Card
    $c.ForeColor = $script:Pal.Text
    $c.Font = $script:FBody
    $c.FlatStyle = 'Flat'
    $c.Add_DrawItem({
        param($s, $e)
        $g = $e.Graphics
        $pal = $script:Pal
        $txt = if ($e.Index -ge 0) { [string]$s.Items[$e.Index] } else { $s.Text }
        $r = New-Object System.Drawing.Rectangle($e.Bounds.X, $e.Bounds.Y, $e.Bounds.Width, $e.Bounds.Height)
        if (($e.State -band [System.Windows.Forms.DrawItemState]::Selected) -ne 0) {
            $br = New-Object System.Drawing.SolidBrush($pal.CardHi)
            $g.FillRectangle($br, $r); $br.Dispose()
        }
        $flags = [System.Windows.Forms.TextFormatFlags]::VerticalCenter -bor
        [System.Windows.Forms.TextFormatFlags]::EndEllipsis
        [System.Windows.Forms.TextRenderer]::DrawText($g, $txt, $script:FBody, $r, $pal.Text, $flags)
    })
    return $c
}

function New-GameRadio {
    param([string]$Text, [int]$X, [int]$Y, [int]$W, [int]$H)
    $r = New-Object System.Windows.Forms.RadioButton
    $r.Text = $Text
    $r.Tag = 'segment'
    $r.Location = New-Object System.Drawing.Point($X, $Y)
    $r.Size = New-Object System.Drawing.Size($W, $H)
    $r.Appearance = 'Button'
    $r.FlatStyle = 'Flat'
    $r.FlatAppearance.BorderSize = 0
    $r.FlatAppearance.MouseOverBackColor = $script:Pal.Card
    $r.BackColor = $script:Pal.Card
    $r.ForeColor = $script:Pal.TextDim
    $r.Cursor = [System.Windows.Forms.Cursors]::Hand
    $r.Add_Paint({
        param($s, $e)
        try {
            $g = $e.Graphics
            $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
            $pal = $script:Pal
            $path = Get-RoundPath 1 1 ($s.Width - 2) ($s.Height - 2) 5
            if ($s.Checked) {
                $br = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(22, 46, 58))
                $g.FillPath($br, $path); $br.Dispose()
                $pen = New-Object System.Drawing.Pen($pal.Accent, 1)
                $g.DrawPath($pen, $path); $pen.Dispose()
                $tx = $pal.Accent
            } else {
                $h = $script:BtnState[$s.GetHashCode()].Hover
                $br = New-Object System.Drawing.SolidBrush($(if ($h) { $pal.CardHi } else { $pal.Card }))
                $g.FillPath($br, $path); $br.Dispose()
                $pen = New-Object System.Drawing.Pen($(if ($h) { $pal.Line } else { $pal.Line }), 1)
                $g.DrawPath($pen, $path); $pen.Dispose()
                $tx = [System.Drawing.Color]::FromArgb(150, 158, 176)
            }
            $path.Dispose()
            $flags = [System.Windows.Forms.TextFormatFlags]::HorizontalCenter -bor
            [System.Windows.Forms.TextFormatFlags]::VerticalCenter -bor
            [System.Windows.Forms.TextFormatFlags]::EndEllipsis
            $inner = New-Object System.Drawing.Rectangle(8, 0, ($s.Width - 16), $s.Height)
            [System.Windows.Forms.TextRenderer]::DrawText($g, $s.Text, $script:FBtn, $inner, $tx, $flags)
        } catch {
            Write-VpnLog ('radio paint error: ' + $_.Exception.Message)
        }
    })
    $r.Add_MouseEnter({ $script:BtnState[$this.GetHashCode()] = @{ Hover = $true; Down = $false }; $this.Invalidate() })
    $r.Add_MouseLeave({ $script:BtnState[$this.GetHashCode()] = @{ Hover = $false; Down = $false }; $this.Invalidate() })
    $r.Add_CheckedChanged({ $this.Invalidate() })
    $script:BtnState[$r.GetHashCode()] = @{ Hover = $false; Down = $false }
    return $r
}

function New-GameTextBox {
    param([int]$X, [int]$Y, [int]$W, [int]$H, [string]$Text)
    $t = New-Object System.Windows.Forms.TextBox
    $t.Location = New-Object System.Drawing.Point($X, $Y)
    $t.Size = New-Object System.Drawing.Size($W, $H)
    $t.Text = $Text
    $t.Font = $script:FMono
    $t.BackColor = $script:Pal.Card
    $t.ForeColor = $script:Pal.Text
    $t.BorderStyle = 'FixedSingle'
    return $t
}

function New-GameCaption {
    param([string]$Text, [int]$X, [int]$Y, [int]$W, [string]$Color = 'TextDim')
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $Text
    $l.Tag = $Color
    $l.Location = New-Object System.Drawing.Point($X, $Y)
    $l.Size = New-Object System.Drawing.Size($W, 14)
    $l.AutoSize = $false
    $l.Font = $script:FCaps
    $l.ForeColor = $script:Pal[$Color]
    $l.BackColor = [System.Drawing.Color]::Transparent
    return $l
}

function New-GameLed {
    param([int]$X, [int]$Y, [int]$D = 10)
    $p = New-Object System.Windows.Forms.Panel
    $p.Location = New-Object System.Drawing.Point($X, $Y)
    $p.Size = New-Object System.Drawing.Size($D, $D)
    $p.BackColor = [System.Drawing.Color]::Transparent
    $p.Tag = 'off'
    $p.Add_Paint({
        param($s, $e)
        $g = $e.Graphics
        $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $st = [string]$s.Tag
        $c = switch ($st) {
            'ok' { $script:Pal.Accent2 }
            'busy' { $script:Pal.Accent }
            'err' { $script:Pal.Danger }
            default { $script:Pal.Muted }
        }
        $d = $s.Width
        $br = New-Object System.Drawing.SolidBrush($c)
        $g.FillEllipse($br, 0, 0, $d, $d)
        $br.Dispose()
        $glow = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(70, $c.R, $c.G, $c.B))
        $g.FillEllipse($glow, -2, -2, ($d + 4), ($d + 4))
        $glow.Dispose()
    })
    return $p
}

function Install-GameTitleBar {
    param($Form, [int]$Height = 46)
    $panel = New-Object System.Windows.Forms.Panel
    $panel.Dock = 'Top'
    $panel.Height = $Height
    $panel.BackColor = $script:Pal.Bg2
    $panel.Tag = 'titlebar'

    $capClose = New-GameButton '' ($Form.ClientSize.Width - 40) 8 32 30 'danger'
    $capMin = New-GameButton '' ($Form.ClientSize.Width - 74) 8 32 30 'ghost'
    $led = New-GameLed ($Form.ClientSize.Width - 104) ([int](($Height - 10) / 2)) 10
    $panel.Controls.Add($capClose)
    $panel.Controls.Add($capMin)
    $panel.Controls.Add($led)

    $capClose.Add_Click({ $Form.Close() })
    $capMin.Add_Click({ $Form.WindowState = 'Minimized' })

    $panel.Add_Paint({
        param($s, $e)
        try {
            $g = $e.Graphics
            $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
            $pal = $script:Pal
            $w = $s.Width; $h = $s.Height
            $p0 = New-Object System.Drawing.Point -ArgumentList 0, 0
            $p1 = New-Object System.Drawing.Point -ArgumentList 0, $h
            $br = New-Object System.Drawing.Drawing2D.LinearGradientBrush -ArgumentList $p0, $p1, $pal.Bg2, $pal.Bg
            $rectAll = New-Object System.Drawing.Rectangle -ArgumentList 0, 0, $w, $h
            $g.FillRectangle($br, $rectAll)
            $br.Dispose()
            $pen = New-Object System.Drawing.Pen -ArgumentList $pal.Line, 1
            $g.DrawLine($pen, 0, ($h - 1), $w, ($h - 1))
            $pen.Dispose()
            $ac = New-Object System.Drawing.SolidBrush -ArgumentList $pal.Accent
            $g.FillRectangle($ac, (New-Object System.Drawing.Rectangle -ArgumentList 0, 0, 3, $h))
            $ac.Dispose()

            $flagsV = [System.Windows.Forms.TextFormatFlags]::NoPadding
            $big = New-Object System.Drawing.Size -ArgumentList 10000, 100
            $wMain = [System.Windows.Forms.TextRenderer]::MeasureText('VPN ЛАУНЧЕР', $script:FLogo, $big, $flagsV).Width
            $wBy = [System.Windows.Forms.TextRenderer]::MeasureText('by @YoncFALL', $script:FSub, $big, $flagsV).Width
            $ty = [int](($h - 22) / 2)
            $ptMain = New-Object System.Drawing.Point -ArgumentList 16, $ty
            $ptBy = New-Object System.Drawing.Point -ArgumentList (16 + $wMain + 10), ([int](($h - 14) / 2) + 3)
            [System.Windows.Forms.TextRenderer]::DrawText($g, 'VPN ЛАУНЧЕР', $script:FLogo, $ptMain, $pal.Accent, $flagsV)
            [System.Windows.Forms.TextRenderer]::DrawText($g, 'by @YoncFALL', $script:FSub, $ptBy, $pal.TextDim, $flagsV)
        } catch {
            Write-VpnLog ('titlebar paint error: ' + $_.Exception.Message)
        }
    })

    $panel.Add_MouseDown({
        if ($_.Button -eq [System.Windows.Forms.MouseButtons]::Left) { Start-GameDrag $this.FindForm() }
    })
    foreach ($c in @($led, $capMin, $capClose)) {
        $c.Add_MouseDown({ })
    }

    $Form.Controls.Add($panel)

    # таймер обязан лежать в скриптовой переменной, иначе сборщик мусора его уберёт и он перестанет тикать
    $script:CapLed = $led
    $script:LedTimer = New-Object System.Windows.Forms.Timer
    $script:LedTimer.Interval = 400
    $script:LedTimer.Add_Tick({
        try {
            $st = 'off'
            if ($script:Busy) { $st = 'busy' }
            elseif ($script:Proc) {
                if ($script:Proc.HasExited) { $st = 'err' } else { $st = 'ok' }
            } elseif ($script:Status -and $script:Status.Text -match 'ошибк|не удал') { $st = 'err' }
            foreach ($l in @($script:CapLed, $script:StatusLed)) {
                if ($l -and [string]$l.Tag -ne $st) { $l.Tag = $st; $l.Invalidate() }
            }
        } catch { }
    })
    $script:LedTimer.Start()
    return @{ Panel = $panel; Led = $led }
}

function Install-GameCorners {
    param($Form, [int]$Radius = 12)
    # перетаскивание за любую пустую часть окна, а не только за шапку
    $Form.Add_MouseDown({
        if ($_.Button -eq [System.Windows.Forms.MouseButtons]::Left) { Start-GameDrag $this }
    })
    $apply = {
        $p = Get-RoundPath 0 0 $Form.Width $Form.Height $Radius
        $Form.Region = New-Object System.Drawing.Region -ArgumentList $p
        $p.Dispose()
    }
    $Form.Add_Shown($apply)
    $Form.Add_Resize({
        try { & $apply } catch { }
    })
}
