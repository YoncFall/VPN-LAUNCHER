// Setup.cs - установщик VPN ЛАУНЧЕР.
// Один файл setup.exe: внутри встроен zip с файлами программы.
// Установка идёт в профиль пользователя, права администратора не нужны.
// Запуск: setup.exe            - обычная установка с окном
//        setup.exe /S         - тихая установка
//        setup.exe /DIR="..."  - своя папка
//        setup.exe /NOICONS   - без ярлыков
//        setup.exe /NORUN     - не запускать после установки
//        setup.exe /UNINSTALL - удаление (этим же файлом, скопированным в папку программы)
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

static class Setup
{
    // ---- палитра как в приложении (theme.ps1) ----
    static readonly Color Bg = Color.FromArgb(12, 14, 19);
    static readonly Color Bg2 = Color.FromArgb(18, 21, 29);
    static readonly Color Card = Color.FromArgb(24, 27, 37);
    static readonly Color Line = Color.FromArgb(46, 52, 68);
    static readonly Color Text = Color.FromArgb(230, 234, 242);
    static readonly Color Dim = Color.FromArgb(124, 134, 156);
    static readonly Color Accent = Color.FromArgb(0, 216, 255);
    static readonly Color Accent2 = Color.FromArgb(0, 240, 168);

    const string ProductName = "VPN ЛАУНЧЕР";
    const string ProductId = "YoncFALL_VPN_Launcher";
    const string Version = "1.0.3";
    const string Publisher = "@YoncFALL";
    const string ExeName = "VPNLauncher.exe";
    const string UninstallerName = "uninstall.exe";
    const string UnregKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\" + ProductId;
    const string ShortcutName = "VPN ЛАУНЧЕР BY @YoncFALL";

    static readonly string SelfDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
    static string SelfExe = Assembly.GetEntryAssembly().Location;
    static bool Silent, NoIcons, NoRun;
    static string TargetDir = DefaultDir();

    static string DefaultDir()
    {
        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs", "VPNLauncher");
    }

    [STAThread]
    static int Main(string[] args)
    {
        ParseArgs(args);

        try
        {
            if (HasSwitch("UNINSTALL") || HasSwitch("U")) return Uninstall();
            return Install();
        }
        catch (Exception ex)
        {
            Error("Ошибка установки", ex.Message);
            return 1;
        }
    }

    static void ParseArgs(string[] args)
    {
        foreach (string raw in args)
        {
            string a = raw.Trim().Trim('"');
            if (a.Length == 0) continue;
            string up = a.ToUpperInvariant();
            if (up == "/S" || up == "-S" || up == "/SILENT" || up == "/VERYSILENT") Silent = true;
            else if (up == "/NOICONS" || up == "-NOICONS") NoIcons = true;
            else if (up == "/NORUN" || up == "-NORUN") NoRun = true;
            else if (up.StartsWith("/DIR=")) TargetDir = a.Substring(5).Trim('"').TrimEnd('\\');
        }
    }

    static bool HasSwitch(string name)
    {
        string[] args = Environment.GetCommandLineArgs();
        foreach (string raw in args)
        {
            string a = raw.Trim().Trim('"').TrimStart('/', '-').ToUpperInvariant();
            if (a == name.ToUpperInvariant()) return true;
        }
        return false;
    }

    // ---------------------------------------------------------------- установка

    static int Install()
    {
        if (File.Exists(Path.Combine(TargetDir, ExeName)))
        {
            // это наш собственный деинсталлятор, значит обновление
            string un = Path.Combine(TargetDir, ExeName);
            if (HasSwitch("UNINSTALL")) return 0;
        }

        if (Silent) return RunInstall(null);

        using (Form f = new Form())
        {
            Installer ui = new Installer(f);
            f.ShowDialog();
            return ui.ExitCode;
        }
    }

    // prog: функция отчёта о ходе, null - тихая установка
    static int RunInstall(Action<int, string> prog)
    {
        if (prog == null) prog = delegate { };

        prog(2, "Проверка предыдущей версии");
        string oldDir = RegisteredDir();
        if (!string.IsNullOrEmpty(oldDir) &&
            !string.Equals(oldDir.TrimEnd('\\'), TargetDir.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase))
        {
            RemoveOldInstall(oldDir);
        }

        prog(8, "Копирование файлов");
        string tmp = Path.Combine(Path.GetTempPath(), "vpnlauncher_install_" + Guid.NewGuid().ToString("N").Substring(0, 8));
        try
        {
            Directory.CreateDirectory(tmp);
            prog(14, "Распаковка файлов программы");
            ExtractPayload(tmp, delegate(int p) { prog(14 + p * 54, "Распаковка файлов программы"); });

            prog(72, "Обновление папки программы");
            Directory.CreateDirectory(TargetDir);
            foreach (string f in Directory.GetFiles(tmp))
            {
                string dst = Path.Combine(TargetDir, Path.GetFileName(f));
                try { File.Copy(f, dst, true); }
                catch (IOException) { TryReplace(dst); File.Copy(f, dst, true); }
            }

            prog(78, "Проверка файлов");
            if (!File.Exists(Path.Combine(TargetDir, ExeName)))
                throw new FileNotFoundException("Не найден " + ExeName + " после копирования.");
            if (!File.Exists(Path.Combine(TargetDir, "VPN.ps1")))
                throw new FileNotFoundException("Не найден VPN.ps1 после копирования.");

            // копия установщика внутри папки программы: ею удаляют программу
            // через "Программы и компоненты", её нельзя запускать как приложение
            prog(82, "Подготовка удаления");
            string unins = Path.Combine(TargetDir, UninstallerName);
            if (!string.Equals(Path.GetFullPath(SelfExe), Path.GetFullPath(unins), StringComparison.OrdinalIgnoreCase))
                File.Copy(SelfExe, unins, true);

            prog(88, "Создание ярлыков");
            MakeShortcuts();

            prog(94, "Регистрация в списке программ");
            Register();

            prog(100, "Готово");
        }
        finally
        {
            try { if (Directory.Exists(tmp)) Directory.Delete(tmp, true); } catch { }
        }

        if (!NoRun && !Silent) StartApp();
        return 0;
    }

    static void TryReplace(string path)
    {
        for (int i = 0; i < 40; i++)
        {
            if (!File.Exists(path)) return;
            try { File.Delete(path); return; }
            catch (IOException) { StopApp(); System.Threading.Thread.Sleep(250); }
            catch (UnauthorizedAccessException) { System.Threading.Thread.Sleep(250); }
        }
    }

    static void ExtractPayload(string dest, Action<int> tick)
    {
        using (Stream s = OpenPayload())
        using (ZipArchive zip = new ZipArchive(s, ZipArchiveMode.Read))
        {
            long total = 0;
            foreach (ZipArchiveEntry e in zip.Entries) total += e.Length;
            long done = 0;
            int lastPct = -1;

            foreach (ZipArchiveEntry e in zip.Entries)
            {
                string name = e.FullName.Replace('/', Path.DirectorySeparatorChar).Replace('\\', Path.DirectorySeparatorChar);
                if (name.Contains("..")) continue;
                string outPath = Path.Combine(dest, name);
                if (name.EndsWith(Path.DirectorySeparatorChar.ToString()) || e.Name.Length == 0)
                {
                    Directory.CreateDirectory(outPath);
                    continue;
                }
                string dir = Path.GetDirectoryName(outPath);
                if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                using (Stream inS = e.Open())
                using (FileStream outS = new FileStream(outPath, FileMode.Create, FileAccess.Write, FileShare.None))
                    inS.CopyTo(outS);

                done += e.Length;
                int pct = total > 0 ? (int)(done * 100 / total) : 100;
                if (pct != lastPct) { lastPct = pct; tick(pct); }
            }
        }
    }

    static Stream OpenPayload()
    {
        Assembly asm = Assembly.GetEntryAssembly();
        string[] names = asm.GetManifestResourceNames();
        foreach (string n in names)
            if (n.EndsWith("payload.zip", StringComparison.OrdinalIgnoreCase))
                return asm.GetManifestResourceStream(n);
        throw new InvalidOperationException("В установщике нет файлов программы (payload.zip не найден).");
    }

    // ---------------------------------------------------------------- ярлыки

    static string DesktopDir()
    {
        return Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
    }

    static string StartMenuDir()
    {
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                            "Microsoft", "Windows", "Start Menu", "Programs", "VPN ЛАУНЧЕР");
    }

    static void MakeShortcuts()
    {
        // /NOICONS означает "не создавать ярлыки", а не "удалить существующие":
        // иначе тихая установка с ключом сносила бы ярлык прежней установки
        if (NoIcons) return;
        string target = Path.Combine(TargetDir, ExeName);
        string icon = target;

        MakeShortcut(Path.Combine(DesktopDir(), ShortcutName + ".lnk"), target, icon,
                     "Установленный VPN-клиент", null);

        string menu = StartMenuDir();
        Directory.CreateDirectory(menu);
        MakeShortcut(Path.Combine(menu, ShortcutName + ".lnk"), target, icon,
                     "Установленный VPN-клиент", null);
        MakeShortcut(Path.Combine(menu, "Удалить VPN ЛАУНЧЕР.lnk"), Path.Combine(TargetDir, UninstallerName), icon,
                     "Удаление программы", "/UNINSTALL");

        // иконка приложения рядом с exe, чтобы её подхватил проводник и окно.
        // Берём из ресурса установщика: копировать самого себя нельзя,
        // иначе в app.ico попадёт весь установщик целиком.
        WriteAppIcon();
    }

    static void MakeShortcut(string path, string target, string icon, string desc, string args)
    {
        try
        {
            Type t = Type.GetTypeFromProgID("WScript.Shell");
            object sh = Activator.CreateInstance(t);
            object lnk = t.InvokeMember("CreateShortcut", System.Reflection.BindingFlags.InvokeMethod, null, sh, new object[] { path });
            Type lt = lnk.GetType();
            lt.InvokeMember("TargetPath", System.Reflection.BindingFlags.SetProperty, null, lnk, new object[] { target });
            lt.InvokeMember("WorkingDirectory", System.Reflection.BindingFlags.SetProperty, null, lnk, new object[] { TargetDir });
            lt.InvokeMember("IconLocation", System.Reflection.BindingFlags.SetProperty, null, lnk, new object[] { icon + ",0" });
            lt.InvokeMember("Description", System.Reflection.BindingFlags.SetProperty, null, lnk, new object[] { desc });
            if (!string.IsNullOrEmpty(args))
                lt.InvokeMember("Arguments", System.Reflection.BindingFlags.SetProperty, null, lnk, new object[] { args });
            lt.InvokeMember("Save", System.Reflection.BindingFlags.InvokeMethod, null, lnk, null);
        }
        catch (Exception ex) { Log("ярлык " + path + ": " + ex.Message); }
    }

    static void RemoveShortcuts()
    {
        try { File.Delete(Path.Combine(DesktopDir(), ShortcutName + ".lnk")); } catch { }
        try { if (Directory.Exists(StartMenuDir())) Directory.Delete(StartMenuDir(), true); } catch { }
    }

    static byte[] EmbeddedIcon()
    {
        Assembly asm = Assembly.GetEntryAssembly();
        foreach (string n in asm.GetManifestResourceNames())
        {
            if (!n.EndsWith("appicon.ico", StringComparison.OrdinalIgnoreCase)) continue;
            using (Stream s = asm.GetManifestResourceStream(n))
            {
                if (s == null) continue;
                MemoryStream ms = new MemoryStream();
                s.CopyTo(ms);
                return ms.ToArray();
            }
        }
        return null;
    }

    static void WriteAppIcon()
    {
        try
        {
            byte[] data = EmbeddedIcon();
            if (data != null)
            {
                File.WriteAllBytes(Path.Combine(TargetDir, "app.ico"), data);
                return;
            }
            string near = Path.Combine(SelfDir, "app.ico");
            if (File.Exists(near)) File.Copy(near, Path.Combine(TargetDir, "app.ico"), true);
        }
        catch (Exception ex) { Log("иконка: " + ex.Message); }
    }

    // ---------------------------------------------------------------- реестр

    static void Register()
    {
        try
        {
            string unins = Path.Combine(TargetDir, UninstallerName);
            using (Microsoft.Win32.RegistryKey k = Microsoft.Win32.Registry.CurrentUser.CreateSubKey(UnregKey))
            {
                k.SetValue("DisplayName", ShortcutName);
                k.SetValue("DisplayVersion", Version);
                k.SetValue("Publisher", "YoncFALL");
                k.SetValue("DisplayIcon", Path.Combine(TargetDir, ExeName) + ",0");
                k.SetValue("InstallLocation", TargetDir);
                k.SetValue("UninstallString", "\"" + unins + "\" /UNINSTALL");
                k.SetValue("QuietUninstallString", "\"" + unins + "\" /UNINSTALL /S");
                k.SetValue("InstallDate", DateTime.Now.ToString("yyyyMMdd"));
                k.SetValue("NoModify", 1);
                k.SetValue("NoRepair", 1);
                k.SetValue("EstimatedSize", EstimateSize());
            }
        }
        catch (Exception ex) { Log("реестр: " + ex.Message); }
    }

    static int EstimateSize()
    {
        try
        {
            // деинсталлятор не считаем: это копия setup.exe, а не часть программы
            int sum = 0;
            foreach (string f in Directory.GetFiles(TargetDir))
            {
                if (string.Equals(Path.GetFileName(f), UninstallerName, StringComparison.OrdinalIgnoreCase)) continue;
                sum += (int)Math.Min(int.MaxValue, new FileInfo(f).Length);
            }
            return sum / 1024;
        }
        catch { return 0; }
    }

    static string RegisteredDir()
    {
        try
        {
            using (Microsoft.Win32.RegistryKey k = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(UnregKey))
            {
                if (k == null) return null;
                return k.GetValue("InstallLocation") as string;
            }
        }
        catch { return null; }
    }

    // ---------------------------------------------------------------- удаление

    static int Uninstall()
    {
        // Удалять надо ту папку, где стоит программа, а не ту, откуда запущен
        // установщик: иначе setup.exe /UNINSTALL снёс бы сам себя с папкой dist
        string dir = SelfDir;
        if (!File.Exists(Path.Combine(dir, ExeName)))
        {
            string reg = RegisteredDir();
            if (!string.IsNullOrEmpty(reg) && File.Exists(Path.Combine(reg, ExeName))) dir = reg;
        }

        string regDir = RegisteredDir();
        bool silent = Silent;

        if (!silent)
        {
            DialogResult r = Ask(
                "Удалить " + ProductName + "?\r\n\r\nПрограмма, ярлыки и настройки будут удалены.\r\nПодписки и данные sing-box останутся на диске.",
                "Удаление программы",
                MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
            if (r != DialogResult.Yes) return 0;
        }

        StopApp();
        string menu = StartMenuDir();
        try { File.Delete(Path.Combine(DesktopDir(), ShortcutName + ".lnk")); } catch { }
        try { Microsoft.Win32.Registry.CurrentUser.DeleteSubKeyTree(UnregKey, false); } catch { }

        if (!Directory.Exists(dir) && !Directory.Exists(menu)) return 0;

        // папки нельзя удалить, пока из них запущен сам деинсталлятор,
        // поэтому удаление выполняет отдельная команда после выхода
        StringBuilder cmds = new StringBuilder();
        cmds.Append("/c \"timeout /t 2 /nobreak >nul & ");
        bool first = true;
        foreach (string d in new string[] { dir, menu })
        {
            if (!Directory.Exists(d)) continue;
            if (!first) cmds.Append(" & ");
            cmds.Append("rmdir /s /q \"").Append(d.TrimEnd('\\')).Append("\"");
            first = false;
        }
        cmds.Append("\"");
        if (first) return 0;

        Process p = new Process();
        p.StartInfo.FileName = "cmd.exe";
        p.StartInfo.Arguments = cmds.ToString();
        p.StartInfo.UseShellExecute = false;
        p.StartInfo.CreateNoWindow = true;
        p.StartInfo.WindowStyle = ProcessWindowStyle.Hidden;
        try { p.Start(); } catch (Exception ex) { Log("удаление папок: " + ex.Message); }

        return 0;
    }

    static void RemoveOldInstall(string oldDir)
    {
        try
        {
            string un = Path.Combine(oldDir, ExeName);
            if (File.Exists(un))
            {
                Process p = new Process();
                p.StartInfo.FileName = un;
                p.StartInfo.Arguments = "/UNINSTALL /S";
                p.StartInfo.UseShellExecute = false;
                p.StartInfo.CreateNoWindow = true;
                p.StartInfo.WindowStyle = ProcessWindowStyle.Hidden;
                p.Start();
                p.WaitForExit(30000);
            }
            else if (Directory.Exists(oldDir))
            {
                Directory.Delete(oldDir, true);
            }
        }
        catch (Exception ex) { Log("старая установка " + oldDir + ": " + ex.Message); }
    }

    // ---------------------------------------------------------------- процессы

    static void StopApp()
    {
        try
        {
            string reg = RegisteredDir();
            foreach (Process p in Process.GetProcessesByName("VPNLauncher"))
            {
                try
                {
                    string path = p.MainModule.FileName;
                    bool ours = path.StartsWith(TargetDir, StringComparison.OrdinalIgnoreCase)
                             || path.StartsWith(SelfDir, StringComparison.OrdinalIgnoreCase)
                             || (!string.IsNullOrEmpty(reg) && path.StartsWith(reg, StringComparison.OrdinalIgnoreCase));
                    if (!ours) continue;
                    p.CloseMainWindow();
                    p.WaitForExit(4000);
                    if (!p.HasExited) p.Kill();
                }
                catch { }
            }
        }
        catch { }
    }

    static void StartApp()
    {
        try
        {
            Process p = new Process();
            p.StartInfo.FileName = Path.Combine(TargetDir, ExeName);
            p.StartInfo.WorkingDirectory = TargetDir;
            p.StartInfo.UseShellExecute = true;
            p.Start();
        }
        catch (Exception ex) { Log("запуск: " + ex.Message); }
    }

    // ---------------------------------------------------------------- окно установки

    class Installer
    {
        readonly Form f;
        readonly Panel welcome, busy, done;
        TextBox dirBox;
        CheckBox deskBox, runBox;
        Label status;
        ProgressBar bar;
        Button go, cancel;
        readonly string origDir = TargetDir;
        public int ExitCode = 0;

        public Installer(Form form)
        {
            f = form;
            ExitCode = 1;

            f.Text = "Установка " + ProductName;
            f.FormBorderStyle = FormBorderStyle.FixedDialog;
            f.StartPosition = FormStartPosition.CenterScreen;
            f.ClientSize = new Size(520, 380);
            f.BackColor = Bg;
            f.ForeColor = Text;
            f.Font = new Font("Segoe UI", 9f);
            f.MinimizeBox = false;
            f.MaximizeBox = false;
            f.FormClosing += delegate
            {
                if (ExitCode == 1) { TargetDir = origDir; ExitCode = 0; }
            };

            welcome = new Panel { Dock = DockStyle.Fill, BackColor = Bg, Padding = new Padding(24) };
            busy = new Panel { Dock = DockStyle.Fill, BackColor = Bg, Padding = new Padding(24), Visible = false };
            done = new Panel { Dock = DockStyle.Fill, BackColor = Bg, Padding = new Padding(24), Visible = false };

            f.Controls.Add(welcome);
            f.Controls.Add(busy);
            f.Controls.Add(done);

            BuildWelcome();
            BuildBusy();
            BuildDone();
        }

        Label Head(string t, int size, Color c, int top)
        {
            Label l = new Label
            {
                Text = t,
                ForeColor = c,
                Font = new Font("Segoe UI", size, size > 10 ? FontStyle.Bold : FontStyle.Regular),
                AutoSize = true,
                Location = new Point(0, top)
            };
            welcome.Controls.Add(l);
            return l;
        }

        void BuildWelcome()
        {
            PictureBox logo = new PictureBox
            {
                Size = new Size(64, 64),
                Location = new Point(0, 0),
                SizeMode = PictureBoxSizeMode.StretchImage
            };
            try
            {
                Stream icoStream = OpenSelfIco();
                if (icoStream != null)
                {
                    using (Icon ico = new Icon(icoStream)) logo.Image = ico.ToBitmap();
                }
            }
            catch { }
            welcome.Controls.Add(logo);

            Label t1 = new Label
            {
                Text = ProductName,
                ForeColor = Text,
                Font = new Font("Segoe UI", 18f, FontStyle.Bold),
                AutoSize = true,
                Location = new Point(84, 2)
            };
            welcome.Controls.Add(t1);
            Label t2 = new Label
            {
                Text = "версия " + Version + "   ·   " + Publisher,
                ForeColor = Dim,
                AutoSize = true,
                Location = new Point(84, 36)
            };
            welcome.Controls.Add(t2);

            Label pathL = new Label
            {
                Text = "Папка установки",
                ForeColor = Text,
                AutoSize = true,
                Location = new Point(0, 96)
            };
            welcome.Controls.Add(pathL);

            dirBox = new TextBox
            {
                Text = TargetDir,
                Location = new Point(0, 118),
                Width = 470,
                BackColor = Card,
                ForeColor = Text,
                BorderStyle = BorderStyle.FixedSingle
            };
            welcome.Controls.Add(dirBox);

            deskBox = new CheckBox
            {
                Text = "Создать ярлык на рабочем столе",
                Checked = !NoIcons,
                ForeColor = Text,
                AutoSize = true,
                Location = new Point(0, 158),
                FlatStyle = FlatStyle.Flat,
                BackColor = Bg
            };
            deskBox.FlatAppearance.BorderColor = Line;
            welcome.Controls.Add(deskBox);

            runBox = new CheckBox
            {
                Text = "Запустить после установки",
                Checked = !NoRun,
                ForeColor = Text,
                AutoSize = true,
                Location = new Point(0, 184),
                FlatStyle = FlatStyle.Flat,
                BackColor = Bg
            };
            runBox.FlatAppearance.BorderColor = Line;
            welcome.Controls.Add(runBox);

            Label note = new Label
            {
                Text = "Программа ставится в ваш профиль, права администратора не нужны.\r\n" +
                       "Администратор может понадобиться только для режима TUN при подключении.",
                ForeColor = Dim,
                AutoSize = false,
                Size = new Size(470, 60),
                Location = new Point(0, 220)
            };
            welcome.Controls.Add(note);

            go = BigButton("Установить", Accent, 300);
            go.Click += delegate { Start(); };
            welcome.Controls.Add(go);

            cancel = BigButton("Отмена", Card, 300);
            cancel.Width = 120;
            cancel.Location = new Point(350, 300);
            cancel.Click += delegate { f.Close(); };
            welcome.Controls.Add(cancel);
        }

        Stream OpenSelfIco()
        {
            foreach (string n in Assembly.GetEntryAssembly().GetManifestResourceNames())
                if (n.EndsWith("appicon.ico", StringComparison.OrdinalIgnoreCase))
                    return Assembly.GetEntryAssembly().GetManifestResourceStream(n);
            string p = Path.Combine(SelfDir, "app.ico");
            return File.Exists(p) ? File.OpenRead(p) : null;
        }

        Button BigButton(string text, Color back, int top)
        {
            Button b = new Button
            {
                Text = text,
                Location = new Point(0, top),
                Size = new Size(320, 44),
                FlatStyle = FlatStyle.Flat,
                BackColor = back,
                ForeColor = back == Accent ? Color.FromArgb(2, 26, 34) : Text,
                Cursor = Cursors.Hand,
                Font = new Font("Segoe UI", 10f, FontStyle.Bold)
            };
            b.FlatAppearance.BorderSize = 0;
            b.FlatAppearance.MouseOverBackColor = ControlPaint.Light(back, 0.12f);
            return b;
        }

        void BuildBusy()
        {
            Label h = new Label
            {
                Text = "Установка",
                ForeColor = Text,
                Font = new Font("Segoe UI", 14f, FontStyle.Bold),
                AutoSize = true,
                Location = new Point(0, 60)
            };
            busy.Controls.Add(h);

            status = new Label
            {
                Text = "Подготовка",
                ForeColor = Dim,
                AutoSize = false,
                Size = new Size(470, 24),
                Location = new Point(0, 100)
            };
            busy.Controls.Add(status);

            bar = new ProgressBar
            {
                Style = ProgressBarStyle.Continuous,
                Location = new Point(0, 130),
                Size = new Size(470, 10),
                BackColor = Bg2,
                ForeColor = Accent
            };
            busy.Controls.Add(bar);
        }

        void BuildDone()
        {
            Label big = new Label
            {
                Text = "Установлено",
                ForeColor = Accent2,
                Font = new Font("Segoe UI", 20f, FontStyle.Bold),
                AutoSize = true,
                Location = new Point(0, 70)
            };
            done.Controls.Add(big);

            Label d = new Label
            {
                Text = ProductName + " " + Version + " готова к работе.\r\n\r\nПрограмма: " + TargetDir,
                ForeColor = Text,
                AutoSize = false,
                Size = new Size(470, 70),
                Location = new Point(0, 112)
            };
            done.Controls.Add(d);

            Button open = BigButton("Запустить", Accent, 210);
            open.Click += delegate { StartApp(); ExitCode = 0; f.Close(); };
            done.Controls.Add(open);

            Button close = BigButton("Закрыть", Card, 210);
            close.Width = 120;
            close.Location = new Point(350, 210);
            close.Click += delegate { ExitCode = 0; f.Close(); };
            done.Controls.Add(close);
        }

        void Start()
        {
            string chosen = dirBox.Text.Trim();
            if (chosen.Length == 0) { Error("Нужна папка установки", "Укажите папку, куда поставить программу."); return; }
            try
            {
                if (chosen.Length > 3) chosen = chosen.TrimEnd('\\');
                Directory.CreateDirectory(chosen);
                chosen = new DirectoryInfo(chosen).FullName;
            }
            catch (Exception ex)
            {
                Error("Не могу создать папку", chosen + "\r\n\r\n" + ex.Message);
                return;
            }

            TargetDir = chosen;
            NoIcons = !deskBox.Checked;
            NoRun = !runBox.Checked;

            welcome.Visible = false;
            busy.Visible = true;
            f.Height = f.Height - 100;
            bar.Style = ProgressBarStyle.Marquee;
            Application.DoEvents();

            int code = 1;
            try
            {
                code = RunInstall(delegate(int pct, string msg)
                {
                    status.Text = msg;
                    bar.Style = ProgressBarStyle.Continuous;
                    bar.Value = Math.Max(0, Math.Min(100, pct));
                    Application.DoEvents();
                });
            }
            catch (Exception ex)
            {
                Error("Установка не завершена", ex.Message);
            }

            if (code == 0)
            {
                if (NoRun) StartApp();
                busy.Visible = false;
                done.Visible = true;
                Application.DoEvents();
            }
            else
            {
                ExitCode = code;
                f.Close();
            }
        }
    }

    // ---------------------------------------------------------------- мелочи

    static DialogResult Ask(string text, string title, MessageBoxButtons buttons, MessageBoxIcon icon)
    {
        return MessageBox.Show(text, title, buttons, icon);
    }

    static void Error(string title, string text)
    {
        MessageBox.Show(text, title, MessageBoxButtons.OK, MessageBoxIcon.Error);
    }

    static void Log(string msg)
    {
        try
        {
            File.AppendAllText(Path.Combine(Path.GetTempPath(), "vpnlauncher_setup.log"),
                DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " " + msg + Environment.NewLine);
        }
        catch { }
    }
}
