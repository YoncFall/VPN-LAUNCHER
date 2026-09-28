# theme.ps1 - оформление MyVPN: тёмная игровая тема (v2).
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

# Нативные элементы интерфейса: скруглённые панели, поля ввода и комбобокс.
if (-not ('GameThemeNative' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public static class GameThemeNative {
    // прямоугольник со скруглёнными углами
    public static GraphicsPath RoundPath(int x, int y, int w, int h, int r) {
        GraphicsPath p = new GraphicsPath();
        if (r < 1) { p.AddRectangle(new Rectangle(x, y, w, h)); return p; }
        int d = Math.Min(r * 2, Math.Min(w, h));
        p.AddArc(x, y, d, d, 180, 90);
        p.AddArc(x + w - d, y, d, d, 270, 90);
        p.AddArc(x + w - d, y + h - d, d, d, 0, 90);
        p.AddArc(x, y + h - d, d, d, 90, 90);
        p.CloseFigure();
        return p;
    }

    public static void Ring(Graphics g, int w, int h, Color c) {
        if (w <= 0 || h <= 0) return;
        using (Pen p = new Pen(c)) g.DrawRectangle(p, 0, 0, w - 1, h - 1);
    }

    // комбобокс: скруглённая рамка, свои углы, кнопка-стрелка вместо нативной
    public static void ComboPaint(ComboBox c, Color frame, Color fill, Color chevron, Color corner, int radius) {
        if (c.Width <= 0 || c.Height <= 0) return;
        using (Graphics g = Graphics.FromHwnd(c.Handle)) {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            int w = c.Width, h = c.Height;
            using (GraphicsPath path = RoundPath(1, 1, w - 2, h - 2, radius)) {
                // закрываем квадратные углы нативной рамки цветом фона
                using (Region reg = new Region(new Rectangle(0, 0, w, h))) {
                    reg.Exclude(path);
                    using (SolidBrush b = new SolidBrush(corner)) g.FillRegion(b, reg);
                }
                using (Pen p = new Pen(frame, 1)) g.DrawPath(p, path);
            }
            // кнопка-стрелка: скруглённая, со своей рамкой и градиентом
            int bw = 22;
            int by = 2;
            int bh = h - 4;
            using (GraphicsPath bp = RoundPath(w - bw + 2, by, bw - 4, bh - 1, radius - 2)) {
                using (LinearGradientBrush b = new LinearGradientBrush(
                    new Point(0, 0), new Point(0, h),
                    Color.FromArgb(32, 36, 48), Color.FromArgb(24, 27, 37))) {
                    g.FillPath(b, bp);
                }
                using (Pen p = new Pen(frame, 1)) g.DrawPath(p, bp);
            }
            // шеврон
            int cx = w - bw + 4, cy = h / 2;
            Point[] pts = { new Point(cx - 4, cy - 1), new Point(cx + 4, cy - 1), new Point(cx, cy + 3) };
            using (SolidBrush b = new SolidBrush(chevron)) g.FillPolygon(b, pts);
        }
    }
}

// Скруглённое поле ввода: панель рисует рамку и фон, внутри - бесшовный TextBox.
public class GameField : System.Windows.Forms.Panel {
    public TextBox Inner;
    public Color FillColor = Color.FromArgb(19, 22, 30);
    public Color BorderColor = Color.FromArgb(58, 66, 86);
    public Color BorderHover = Color.FromArgb(96, 108, 138);
    public Color BorderFocus = Color.FromArgb(0, 200, 240);
    public int CornerRadius = 7;
    public string Placeholder = "";

    public GameField() {
        this.SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                      ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        this.BackColor = Color.Transparent;
        Inner = new TextBox();
        Inner.BorderStyle = BorderStyle.None;
        Inner.BackColor = FillColor;
        Inner.ForeColor = Color.FromArgb(230, 234, 242);
        Inner.Multiline = false;
        Inner.TextChanged += delegate { this.OnTextChanged(EventArgs.Empty); };
        Inner.GotFocus += delegate { this.Invalidate(); };
        Inner.LostFocus += delegate { this.Invalidate(); };
        this.Controls.Add(Inner);
    }

    public override Font Font {
        get { return base.Font; }
        set { base.Font = value; Inner.Font = value; }
    }

    public override string Text {
        get { return Inner.Text; }
        set { Inner.Text = value; }
    }

    protected override void OnResize(EventArgs e) {
        base.OnResize(e);
        int w = this.ClientSize.Width, h = this.ClientSize.Height;
        Inner.SetBounds(10, Math.Max(2, (h - 20) / 2), Math.Max(10, w - 20), 20);
    }

    protected override void OnPaint(PaintEventArgs e) {
        Graphics g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
        int w = this.ClientSize.Width, h = this.ClientSize.Height;
        using (GraphicsPath path = GameThemeNative.RoundPath(1, 1, w - 2, h - 2, CornerRadius)) {
            using (SolidBrush b = new SolidBrush(FillColor)) g.FillPath(b, path);
            Color line = Inner.Focused ? BorderFocus : (this.Controls.Count > 0 && this.ClientRectangle.Contains(PointToClient(Cursor.Position)) ? BorderHover : BorderColor);
            using (Pen p = new Pen(line, 1)) g.DrawPath(p, path);
            if (Inner.Focused) {
                // мягкое свечение вокруг активного поля
                using (Pen glow = new Pen(Color.FromArgb(60, BorderFocus.R, BorderFocus.G, BorderFocus.B), 3)) {
                    g.DrawPath(glow, path);
                }
            }
            // подсказка в пустом поле
            if (Inner.Text.Length == 0 && !Inner.Focused && Placeholder.Length > 0) {
                using (SolidBrush ph = new SolidBrush(Color.FromArgb(110, 118, 136))) {
                    TextRenderer.DrawText(g, Placeholder, Inner.Font,
                        new Rectangle(12, 1, Math.Max(10, w - 24), h - 2), ph.Color,
                        TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
                }
            }
        }
    }

    protected override void OnMouseEnter(EventArgs e) { base.OnMouseEnter(e); this.Invalidate(); }
    protected override void OnMouseLeave(EventArgs e) { base.OnMouseLeave(e); this.Invalidate(); }
    protected override void OnClick(EventArgs e) {
        base.OnClick(e);
        if (!Inner.Focused) { Inner.Focus(); }
    }
}

// Скруглённая рамка-стакан: фон и граница (под списки и области)
public class GameFrame : System.Windows.Forms.Panel {
    public Color FillColor = Color.FromArgb(18, 21, 29);
    public Color BorderColor = Color.FromArgb(46, 52, 68);
    public int CornerRadius = 10;

    public GameFrame() {
        this.SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                      ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        this.BackColor = Color.Transparent;
    }

    protected override void OnPaint(PaintEventArgs e) {
        Graphics g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        int w = this.ClientSize.Width, h = this.ClientSize.Height;
        using (GraphicsPath path = GameThemeNative.RoundPath(1, 1, w - 2, h - 2, CornerRadius)) {
            using (SolidBrush b = new SolidBrush(FillColor)) g.FillPath(b, path);
            using (Pen p = new Pen(BorderColor, 1)) g.DrawPath(p, path);
            // тонкий блик сверху
            using (Pen hi = new Pen(Color.FromArgb(70, 255, 255, 255), 1)) {
                Rectangle rr = Rectangle.Truncate(path.GetBounds());
                g.DrawLine(hi, rr.X + CornerRadius, rr.Y + 1, rr.Right - CornerRadius, rr.Y + 1);
            }
        }
    }
}

public class GameTextBox : GameField {
}

public class GameComboBox : ComboBox {
    public Color FrameColor = Color.FromArgb(58, 66, 86);
    public Color FillColor = Color.FromArgb(19, 22, 30);
    public Color Chevron = Color.FromArgb(150, 158, 176);
    public int CornerRadius = 6;

    public GameComboBox() {
        this.SetStyle(ControlStyles.OptimizedDoubleBuffer, true);
    }

    protected override void WndProc(ref Message m) {
        base.WndProc(ref m);
        if (m.Msg == 0x000F) GameThemeNative.ComboPaint(this, FrameColor, FillColor, Chevron, FillColor, CornerRadius);
    }
}
'@ -ReferencedAssemblies 'System.Windows.Forms.dll','System.Drawing.dll'
}

function Start-GameDrag {
    param($Form)
    try {
        [void][MyVpnNative]::ReleaseCapture()
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
    LineHi  = [System.Drawing.Color]::FromArgb(72, 82, 108)
    Field   = [System.Drawing.Color]::FromArgb(19, 22, 30)
    Text    = [System.Drawing.Color]::FromArgb(230, 234, 242)
    TextDim = [System.Drawing.Color]::FromArgb(132, 142, 162)
    Accent  = [System.Drawing.Color]::FromArgb(0, 216, 255)
    AccentD = [System.Drawing.Color]::FromArgb(0, 150, 190)
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
$script:FSub  = Get-GameFont 8
$script:FBtn  = Get-GameFont 8.5 'Bold'
$script:FCaps = Get-GameFont 8 'Bold'
$script:FMono = Get-GameFont 8.5
$script:FRow  = Get-GameFont 9

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

function Set-AA($g) {
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
}

function Get-GradBrush {
    param([System.Drawing.Color]$Top, [System.Drawing.Color]$Bottom, [int]$W, [int]$H)
    $p0 = New-Object System.Drawing.Point(0, 0)
    $p1 = New-Object System.Drawing.Point(0, $H)
    return New-Object System.Drawing.Drawing2D.LinearGradientBrush($p0, $p1, $Top, $Bottom)
}

$script:BtnState = @{}
$script:BtnRadius = @{}

function Set-BtnText($b, [string]$t) {
    $b.Text = $t
    $b.Invalidate()
}

function Get-ButtonSkin {
    param([string]$Kind, [bool]$Hover, [bool]$Down, [bool]$Enabled)
    $pal = $script:Pal
    if (-not $Enabled) {
        return @{
            Top = [System.Drawing.Color]::FromArgb(22, 25, 33)
            Bot = [System.Drawing.Color]::FromArgb(19, 22, 30)
            Line = [System.Drawing.Color]::FromArgb(38, 43, 55)
            Text = [System.Drawing.Color]::FromArgb(74, 81, 98)
        }
    }
    switch ($Kind) {
        'accent' {
            if ($Down) { return @{ Top = [System.Drawing.Color]::FromArgb(0, 140, 178); Bot = [System.Drawing.Color]::FromArgb(0, 110, 148); Line = [System.Drawing.Color]::FromArgb(0, 190, 230); Text = [System.Drawing.Color]::FromArgb(3, 26, 34) } }
            if ($Hover) { return @{ Top = [System.Drawing.Color]::FromArgb(96, 240, 255); Bot = [System.Drawing.Color]::FromArgb(0, 176, 214); Line = [System.Drawing.Color]::FromArgb(120, 246, 255); Text = [System.Drawing.Color]::FromArgb(3, 26, 34) } }
            return @{ Top = [System.Drawing.Color]::FromArgb(46, 226, 255); Bot = [System.Drawing.Color]::FromArgb(0, 160, 205); Line = [System.Drawing.Color]::FromArgb(0, 205, 245); Text = [System.Drawing.Color]::FromArgb(3, 26, 34) }
        }
        'ok' {
            if ($Down) { return @{ Top = [System.Drawing.Color]::FromArgb(0, 156, 110); Bot = [System.Drawing.Color]::FromArgb(0, 128, 92); Line = [System.Drawing.Color]::FromArgb(0, 200, 140); Text = [System.Drawing.Color]::FromArgb(3, 30, 20) } }
            if ($Hover) { return @{ Top = [System.Drawing.Color]::FromArgb(96, 255, 205); Bot = [System.Drawing.Color]::FromArgb(0, 200, 145); Line = [System.Drawing.Color]::FromArgb(120, 255, 220); Text = [System.Drawing.Color]::FromArgb(3, 30, 20) } }
            return @{ Top = [System.Drawing.Color]::FromArgb(52, 246, 180); Bot = [System.Drawing.Color]::FromArgb(0, 178, 128); Line = [System.Drawing.Color]::FromArgb(0, 215, 158); Text = [System.Drawing.Color]::FromArgb(3, 30, 20) }
        }
        'danger' {
            if ($Down) { return @{ Top = [System.Drawing.Color]::FromArgb(175, 44, 72); Bot = [System.Drawing.Color]::FromArgb(150, 34, 58); Line = [System.Drawing.Color]::FromArgb(255, 90, 120); Text = [System.Drawing.Color]::FromArgb(42, 4, 12) } }
            if ($Hover) { return @{ Top = [System.Drawing.Color]::FromArgb(255, 130, 156); Bot = [System.Drawing.Color]::FromArgb(222, 64, 96); Line = [System.Drawing.Color]::FromArgb(255, 150, 174); Text = [System.Drawing.Color]::FromArgb(42, 4, 12) } }
            return @{ Top = [System.Drawing.Color]::FromArgb(255, 104, 132); Bot = [System.Drawing.Color]::FromArgb(196, 48, 78); Line = [System.Drawing.Color]::FromArgb(255, 92, 122); Text = [System.Drawing.Color]::FromArgb(42, 4, 12) }
        }
        'capclose' {
            if ($Hover) { return @{ Top = [System.Drawing.Color]::FromArgb(70, 20, 30); Bot = [System.Drawing.Color]::FromArgb(58, 14, 24); Line = $pal.Danger; Text = $pal.Danger } }
            return @{ Top = [System.Drawing.Color]::FromArgb(18, 21, 29); Bot = [System.Drawing.Color]::FromArgb(16, 19, 26); Line = $pal.Line; Text = [System.Drawing.Color]::FromArgb(150, 158, 176) }
        }
        'capmin' {
            if ($Hover) { return @{ Top = $pal.CardHi; Bot = [System.Drawing.Color]::FromArgb(28, 32, 43); Line = [System.Drawing.Color]::FromArgb(90, 100, 128); Text = $pal.Text } }
            return @{ Top = [System.Drawing.Color]::FromArgb(18, 21, 29); Bot = [System.Drawing.Color]::FromArgb(16, 19, 26); Line = $pal.Line; Text = [System.Drawing.Color]::FromArgb(150, 158, 176) }
        }
        default {
            if ($Down) { return @{ Top = [System.Drawing.Color]::FromArgb(17, 20, 28); Bot = [System.Drawing.Color]::FromArgb(15, 17, 24); Line = $pal.Line; Text = $pal.TextDim } }
            if ($Hover) { return @{ Top = [System.Drawing.Color]::FromArgb(31, 37, 50); Bot = [System.Drawing.Color]::FromArgb(25, 29, 40); Line = $pal.LineHi; Text = $pal.Text } }
            return @{ Top = [System.Drawing.Color]::FromArgb(27, 31, 42); Bot = [System.Drawing.Color]::FromArgb(21, 24, 32); Line = $pal.Line; Text = [System.Drawing.Color]::FromArgb(176, 184, 200) }
        }
    }
}

function New-GameButton {
    param([string]$Text, [int]$X, [int]$Y, [int]$W, [int]$H, [string]$Kind = 'ghost', [int]$Radius = 8)
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
            Set-AA $g
            $path = Get-RoundPath 1 1 ($s.Width - 2) ($s.Height - 2) $script:BtnRadius[$s.GetHashCode()]
            $skin = Get-ButtonSkin ([string]$s.Tag) ([bool]$script:BtnState[$s.GetHashCode()].Hover) ([bool]$script:BtnState[$s.GetHashCode()].Down) $s.Enabled
            $br = Get-GradBrush $skin.Top $skin.Bot $s.Width $s.Height
            $g.FillPath($br, $path)
            $br.Dispose()
            if ($s.Enabled) {
                $pen = New-Object System.Drawing.Pen($skin.Line, 1)
                $g.DrawPath($pen, $path)
                $pen.Dispose()
                # блик сверху у заполненных кнопок
                $hi = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(60, 255, 255, 255), 1)
                $g.DrawLine($hi, 4, 2, ($s.Width - 5), 2)
                $hi.Dispose()
            }
            $path.Dispose()
            $flags = [System.Windows.Forms.TextFormatFlags]::HorizontalCenter -bor
                [System.Windows.Forms.TextFormatFlags]::VerticalCenter -bor
                [System.Windows.Forms.TextFormatFlags]::EndEllipsis
            $inner = New-Object System.Drawing.Rectangle(6, 0, ($s.Width - 12), $s.Height)
            if ($s.Tag -in @('capmin', 'capclose')) {
                # крестик/минус рисуем сами: аккуратные линии из точек
                $c = [System.Drawing.Pen]::new($skin.Text, [single]1.8)
                $c.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
                $c.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
                if ($s.Tag -eq 'capclose') {
                    $g.DrawLine($c, 11, 9, ($s.Width - 11), ($s.Height - 9))
                    $g.DrawLine($c, ($s.Width - 11), 9, 11, ($s.Height - 9))
                } else {
                    $g.DrawLine($c, 9, ([int]($s.Height / 2)), ($s.Width - 9), ([int]($s.Height / 2)))
                }
                $c.Dispose()
            } else {
                [System.Windows.Forms.TextRenderer]::DrawText($g, $s.Text, $script:FBtn, $inner, $skin.Text, $flags)
            }
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
    $script:BtnRadius[$b.GetHashCode()] = $Radius
    return $b
}

function Set-GameListDraw {
    param($List, [bool]$Ping = $false, [int]$LeftPad = 8)
    $List.DrawMode = 'OwnerDrawFixed'
    $List.BorderStyle = 'None'
    $List.BackColor = $script:Pal.Bg2
    $List.ForeColor = $script:Pal.Text
    $List.Add_DrawItem({
        param($s, $e)
        if ($e.Index -lt 0 -or $e.Index -ge $s.Items.Count) { return }
        try {
            $g = $e.Graphics
            Set-AA $g
            $pal = $script:Pal
            $sel = ($e.State -band [System.Windows.Forms.DrawItemState]::Selected) -ne 0
            $rowY = $e.Bounds.Y
            $rh = $e.Bounds.Height
            $rectRow = New-Object System.Drawing.Rectangle -ArgumentList $e.Bounds.X, $rowY, $e.Bounds.Width, $rh

            if ($sel) {
                # выделенная строка: скруглённая плашка с градиентом и полоской
                $path = Get-RoundPath 3 ($rowY + 2) ($e.Bounds.Width - 6) ($rh - 4) 5
                $br = Get-GradBrush ([System.Drawing.Color]::FromArgb(44, 62, 82)) ([System.Drawing.Color]::FromArgb(28, 44, 62)) ($e.Bounds.Width) $rh
                $g.FillPath($br, $path)
                $br.Dispose()
                $bar = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
                    (New-Object System.Drawing.Point(0, $rowY)), (New-Object System.Drawing.Point(0, $rowY + $rh)),
                    $pal.Accent, $pal.AccentD)
                $g.FillRectangle($bar, 6, ($rowY + 4), 3, ($rh - 8))
                $bar.Dispose()
                $path.Dispose()
            } elseif ($e.Index % 2 -eq 1) {
                $br = New-Object System.Drawing.SolidBrush -ArgumentList ([System.Drawing.Color]::FromArgb(22, 25, 34))
                $g.FillRectangle($br, $rectRow)
                $br.Dispose()
            }

            $text = [string]$s.Items[$e.Index]
            $clr = if ($sel) { $pal.Text } else { [System.Drawing.Color]::FromArgb(206, 212, 226) }
            $font = $script:FRow
            $padL = $e.Bounds.X + $LeftPad
            $flags = [System.Windows.Forms.TextFormatFlags]::VerticalCenter -bor [System.Windows.Forms.TextFormatFlags]::EndEllipsis

            if ($Ping -and $e.Index -lt $script:Nodes.Count) {
                $tag = $script:Nodes[$e.Index]['tag']
                $ms = $null
                if ($tag -and $script:Ping.ContainsKey($tag)) { $ms = $script:Ping[$tag] }
                $proto = switch ($script:Nodes[$e.Index]['proto']) {
                    'vless' { 'VLESS' } 'vmess' { 'VMESS' } 'trojan' { 'TROJAN' }
                    'shadowsocks' { 'SS' } 'hysteria2' { 'HY2' } 'tuic' { 'TUIC' } default { '???' }
                }
                $y = $rowY
                $flagsProto = [System.Windows.Forms.TextFormatFlags]::Right -bor [System.Windows.Forms.TextFormatFlags]::VerticalCenter
                $rectProto = New-Object System.Drawing.Rectangle -ArgumentList $padL, $y, 46, $rh
                [System.Windows.Forms.TextRenderer]::DrawText($g, $proto, $script:FCaps, $rectProto, $pal.TextDim, $flagsProto)
                $flagsName = [System.Windows.Forms.TextFormatFlags]::Left -bor
                    [System.Windows.Forms.TextFormatFlags]::VerticalCenter -bor
                    [System.Windows.Forms.TextFormatFlags]::EndEllipsis
                $rectName = New-Object System.Drawing.Rectangle -ArgumentList ($padL + 52), $y, ($e.Bounds.Width - 52 - 92), $rh
                [System.Windows.Forms.TextRenderer]::DrawText($g, [string]$s.Items[$e.Index], $font, $rectName, $clr, $flagsName)
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
                $rectPing = New-Object System.Drawing.Rectangle -ArgumentList $px, $rowY, $psz.Width, $rh
                [System.Windows.Forms.TextRenderer]::DrawText($g, $pingTxt, $font, $rectPing, $pclr, $flags)
            } else {
                $rect = New-Object System.Drawing.Rectangle -ArgumentList $padL, $rowY, ($e.Bounds.Width - $LeftPad - 8), $rh
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

# Скруглённый «стакан» под список: рамка + фон, список внутри с отступом
function New-GameListBox {
    param([int]$X, [int]$Y, [int]$W, [int]$H, [bool]$Ping = $false)
    $fr = New-Object GameFrame
    $fr.Location = New-Object System.Drawing.Point($X, $Y)
    $fr.Size = New-Object System.Drawing.Size($W, $H)
    $l = New-GameList 3 3 ($W - 6) ($H - 6) $Ping
    $fr.Controls.Add($l)
    return @{ Frame = $fr; List = $l }
}

function New-GameCombo {
    param([int]$X, [int]$Y, [int]$W, [int]$H)
    $c = New-Object GameComboBox
    $c.Location = New-Object System.Drawing.Point($X, $Y)
    $c.Size = New-Object System.Drawing.Size($W, $H)
    $c.DropDownStyle = 'DropDown'
    $c.DrawMode = 'OwnerDrawFixed'
    $c.BackColor = $script:Pal.Field
    $c.ForeColor = $script:Pal.Text
    $c.Font = $script:FBody
    $c.FlatStyle = 'Flat'
    $c.ItemHeight = 26
    $c.Add_DrawItem({
        param($s, $e)
        try {
            $g = $e.Graphics
            Set-AA $g
            $pal = $script:Pal
            $txt = if ($e.Index -ge 0) { [string]$s.Items[$e.Index] } else { $s.Text }
            $r = New-Object System.Drawing.Rectangle($e.Bounds.X, $e.Bounds.Y, $e.Bounds.Width, $e.Bounds.Height)
            if (($e.State -band [System.Windows.Forms.DrawItemState]::Selected) -ne 0) {
                $path = Get-RoundPath ($e.Bounds.X + 2) ($e.Bounds.Y + 2) ($e.Bounds.Width - 4) ($e.Bounds.Height - 4) 4
                $br = Get-GradBrush ([System.Drawing.Color]::FromArgb(40, 56, 76)) ([System.Drawing.Color]::FromArgb(28, 44, 62)) $e.Bounds.Width $e.Bounds.Height
                $g.FillPath($br, $path)
                $br.Dispose()
                $path.Dispose()
            }
            $rect = New-Object System.Drawing.Rectangle(($e.Bounds.X + 8), $e.Bounds.Y, ($e.Bounds.Width - 34), $e.Bounds.Height)
            $flags = [System.Windows.Forms.TextFormatFlags]::VerticalCenter -bor
                [System.Windows.Forms.TextFormatFlags]::EndEllipsis
            $col = if (($e.State -band [System.Windows.Forms.DrawItemState]::Selected) -ne 0) { $pal.Text } else { [System.Drawing.Color]::FromArgb(206, 212, 226) }
            [System.Windows.Forms.TextRenderer]::DrawText($g, $txt, $script:FBody, $rect, $col, $flags)
        } catch {
            Write-VpnLog ('combo draw error: ' + $_.Exception.Message)
        }
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
            Set-AA $g
            $pal = $script:Pal
            $path = Get-RoundPath 1 1 ($s.Width - 2) ($s.Height - 2) 8
            $h = $script:BtnState[$s.GetHashCode()].Hover
            if ($s.Checked) {
                $br = Get-GradBrush ([System.Drawing.Color]::FromArgb(24, 52, 68)) ([System.Drawing.Color]::FromArgb(16, 40, 55)) $s.Width $s.Height
                $g.FillPath($br, $path)
                $br.Dispose()
                $pen = New-Object System.Drawing.Pen($pal.Accent, 1)
                $g.DrawPath($pen, $path)
                $pen.Dispose()
                $tx = $pal.Accent
            } else {
                $br = Get-GradBrush $(if ($h) { [System.Drawing.Color]::FromArgb(31, 37, 50) } else { [System.Drawing.Color]::FromArgb(23, 26, 36) }) $(if ($h) { [System.Drawing.Color]::FromArgb(25, 29, 40) } else { [System.Drawing.Color]::FromArgb(19, 22, 31) }) $s.Width $s.Height
                $g.FillPath($br, $path)
                $br.Dispose()
                $pen = New-Object System.Drawing.Pen($(if ($h) { $pal.LineHi } else { $pal.Line }), 1)
                $g.DrawPath($pen, $path)
                $pen.Dispose()
                $tx = if ($h) { $pal.Text } else { [System.Drawing.Color]::FromArgb(150, 158, 176) }
            }
            $path.Dispose()
            $flags = [System.Windows.Forms.TextFormatFlags]::HorizontalCenter -bor
                [System.Windows.Forms.TextFormatFlags]::VerticalCenter -bor
                [System.Windows.Forms.TextFormatFlags]::EndEllipsis
            $inner = New-Object System.Drawing.Rectangle(8, 0, ($s.Width - 16), $s.Height)
            if ($s.Checked) {
                # маленькая точка-индикатор слева от текста
                $dot = New-Object System.Drawing.SolidBrush($pal.Accent)
                $g.FillEllipse($dot, 14, ([int](($s.Height - 6) / 2)), 6, 6)
                $dot.Dispose()
                $inner = New-Object System.Drawing.Rectangle(22, 0, ($s.Width - 28), $s.Height)
            }
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

function New-GameField {
    param([int]$X, [int]$Y, [int]$W, [int]$H, [string]$Text)
    $f = New-Object GameField
    $f.Location = New-Object System.Drawing.Point($X, $Y)
    $f.Size = New-Object System.Drawing.Size($W, $H)
    $f.Text = $Text
    $f.Font = $script:FMono
    $f.ForeColor = $script:Pal.Text
    return $f
}

function New-GameTextBox {
    # старое имя для совместимости
    return New-GameField @PSBoundParameters
}

function New-GameCaption {
    param([string]$Text, [int]$X, [int]$Y, [int]$W, [string]$Color = 'TextDim')
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $Text
    $l.Tag = $Color
    $l.Location = New-Object System.Drawing.Point($X, $Y)
    $l.Size = New-Object System.Drawing.Size($W, 16)
    $l.AutoSize = $false
    $l.Font = $script:FCaps
    $l.ForeColor = $script:Pal[$Color]
    $l.BackColor = [System.Drawing.Color]::Transparent
    return $l
}

function New-GameLabel {
    param([string]$Text, [int]$X, [int]$Y, [int]$W, [int]$H = 18, [string]$Color = 'TextDim', [string]$Font = 'FSub', [string]$Align = 'Left')
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $Text
    $l.Location = New-Object System.Drawing.Point($X, $Y)
    $l.Size = New-Object System.Drawing.Size($W, $H)
    $l.AutoSize = $false
    $l.Font = (Get-Variable -Name $Font -Scope Script -ValueOnly)
    $l.ForeColor = $script:Pal[$Color]
    $l.BackColor = [System.Drawing.Color]::Transparent
    switch ($Align) {
        'MiddleRight' { $l.TextAlign = [System.Drawing.ContentAlignment]::MiddleRight }
        'MiddleLeft' { $l.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft }
        'TopLeft' { $l.TextAlign = [System.Drawing.ContentAlignment]::TopLeft }
        default { $l.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft }
    }
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
        # мягкое свечение
        $gl = New-Object System.Drawing.Drawing2D.GraphicsPath
        $gl.AddEllipse(-2, -2, ($d + 4), ($d + 4))
        $pth = New-Object System.Drawing.Drawing2D.PathGradientBrush($gl)
        $pth.CenterColor = [System.Drawing.Color]::FromArgb(150, $c.R, $c.G, $c.B)
        $pth.SurroundColors = @([System.Drawing.Color]::FromArgb(0, $c.R, $c.G, $c.B))
        $g.FillPath($pth, $gl)
        $pth.Dispose()
        $gl.Dispose()
        # ядро
        $br = New-Object System.Drawing.SolidBrush($c)
        $g.FillEllipse($br, 1, 1, ($d - 2), ($d - 2))
        $br.Dispose()
        # блик
        $hi = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(160, 255, 255, 255))
        $g.FillEllipse($hi, 2, 2, ([Math]::Max(2, [int](($d - 2) * 0.4))), ([Math]::Max(2, [int](($d - 2) * 0.4))))
        $hi.Dispose()
    })
    return $p
}

# Скруглённая карточка-панель, на которой живёт весь контент
function New-GameCard {
    param([int]$X, [int]$Y, [int]$W, [int]$H, [int]$Radius = 14)
    $c = New-Object System.Windows.Forms.Panel
    $c.Location = New-Object System.Drawing.Point($X, $Y)
    $c.Size = New-Object System.Drawing.Size($W, $H)
    $c.BackColor = [System.Drawing.Color]::Transparent
    $c.Tag = $Radius
    $c.Add_Paint({
        param($s, $e)
        try {
            $g = $e.Graphics
            $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
            $pal = $script:Pal
            $r = [int]$s.Tag
            $w = $s.Width; $h = $s.Height
            # мягкое свечение по контуру карточки
            $outer = Get-RoundPath 2 2 ($w - 4) ($h - 4) ($r + 3)
            $glow = New-Object System.Drawing.Drawing2D.PathGradientBrush($outer)
            $glow.CenterColor = [System.Drawing.Color]::FromArgb(26, 24, 34, 46)
            $glow.SurroundColors = @([System.Drawing.Color]::FromArgb(0, 24, 34, 46))
            $g.FillPath($glow, $outer)
            $glow.Dispose()
            $outer.Dispose()
            # сама карточка: лёгкий градиент сверху вниз
            $path = Get-RoundPath 1 1 ($w - 2) ($h - 2) $r
            $br = Get-GradBrush ([System.Drawing.Color]::FromArgb(27, 31, 42)) ([System.Drawing.Color]::FromArgb(22, 25, 34)) $w $h
            $g.FillPath($br, $path)
            $br.Dispose()
            $pen = New-Object System.Drawing.Pen($pal.Line, 1)
            $g.DrawPath($pen, $path)
            $pen.Dispose()
            # акцентная полоска сверху
            $ac = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
                (New-Object System.Drawing.Point($r, 0)), (New-Object System.Drawing.Point(($r + 70), 0)),
                [System.Drawing.Color]::FromArgb(255, $pal.Accent.R, $pal.Accent.G, $pal.Accent.B),
                [System.Drawing.Color]::FromArgb(0, $pal.Accent.R, $pal.Accent.G, $pal.Accent.B))
            $g.FillRectangle($ac, $r, 1, 70, 2)
            $ac.Dispose()
            $path.Dispose()
        } catch {
            Write-VpnLog ('card paint error: ' + $_.Exception.Message)
        }
    })
    return $c
}

# Горизонтальный разделитель
function New-GameDivider {
    param([int]$X, [int]$Y, [int]$W)
    $p = New-Object System.Windows.Forms.Panel
    $p.Location = New-Object System.Drawing.Point($X, $Y)
    $p.Size = New-Object System.Drawing.Size($W, 2)
    $p.BackColor = [System.Drawing.Color]::Transparent
    $p.Add_Paint({
        param($s, $e)
        $g = $e.Graphics
        $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $pal = $script:Pal
        $ln = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(90, $pal.Line.R, $pal.Line.G, $pal.Line.B), 1)
        $g.DrawLine($ln, 0, 1, $s.Width, 1)
        $ln.Dispose()
        # на конце - крошечная точка акцента
        $dot = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(120, $pal.Accent.R, $pal.Accent.G, $pal.Accent.B))
        $g.FillEllipse($dot, ($s.Width - 3), 0, 3, 3)
        $dot.Dispose()
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

    $capClose = New-GameButton '' ($Form.ClientSize.Width - 42) 8 34 30 'capclose' 7
    $capMin = New-GameButton '' ($Form.ClientSize.Width - 80) 8 34 30 'capmin' 7
    $led = New-GameLed ($Form.ClientSize.Width - 116) ([int](($Height - 10) / 2)) 10
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
            $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
            $pal = $script:Pal
            $w = $s.Width; $h = $s.Height
            # фон с лёгким градиентом
            $br = Get-GradBrush ([System.Drawing.Color]::FromArgb(20, 24, 33)) ([System.Drawing.Color]::FromArgb(12, 14, 19)) $w $h
            $g.FillRectangle($br, 0, 0, $w, $h)
            $br.Dispose()
            # нижняя граница
            $pen = New-Object System.Drawing.Pen($pal.Line, 1)
            $g.DrawLine($pen, 0, ($h - 1), $w, ($h - 1))
            $pen.Dispose()
            # акцентный кант слева + тёплый свеловой штрих по низу
            $ac = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
                (New-Object System.Drawing.Point(0, 0)), (New-Object System.Drawing.Point(0, $h)),
                $pal.Accent, $pal.AccentD)
            $g.FillRectangle($ac, 0, 0, 3, $h)
            $ac.Dispose()
            $ac2 = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
                (New-Object System.Drawing.Point(3, 0)), (New-Object System.Drawing.Point([int]($w * 0.4), 0)),
                [System.Drawing.Color]::FromArgb(130, $pal.Accent.R, $pal.Accent.G, $pal.Accent.B),
                [System.Drawing.Color]::FromArgb(0, $pal.Accent.R, $pal.Accent.G, $pal.Accent.B))
            $g.FillRectangle($ac2, 3, ($h - 2), ([Math]::Max(0, [int]($w * 0.4) - 3)), 1)
            $ac2.Dispose()

            # логотип: свечение + основной текст
            $flagsV = [System.Windows.Forms.TextFormatFlags]::NoPadding
            $big = New-Object System.Drawing.Size -ArgumentList 10000, 100
            $wMain = [System.Windows.Forms.TextRenderer]::MeasureText('VPN ЛАУНЧЕР', $script:FLogo, $big, $flagsV).Width
            $wBy = [System.Windows.Forms.TextRenderer]::MeasureText('by @YoncFALL', $script:FSub, $big, $flagsV).Width
            $ty = [int](($h - 22) / 2)
            $ptMain = New-Object System.Drawing.Point -ArgumentList 16, $ty
            # тень/свечение под названием
            $ptGlow = New-Object System.Drawing.Point -ArgumentList 17, ($ty + 1)
            [System.Windows.Forms.TextRenderer]::DrawText($g, 'VPN ЛАУНЧЕР', $script:FLogo, $ptGlow, [System.Drawing.Color]::FromArgb(110, 0, 180, 215), $flagsV)
            [System.Windows.Forms.TextRenderer]::DrawText($g, 'VPN ЛАУНЧЕР', $script:FLogo, $ptMain, $pal.Accent, $flagsV)
            $ptBy = New-Object System.Drawing.Point -ArgumentList (16 + $wMain + 10), ([int](($h - 14) / 2) + 3)
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