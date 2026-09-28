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
    const string Version = "1.0.5";
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
        Log("=== запуск " + ProductName + " " + Version + " ===");
        Log("  ключи      : " + string.Join(" ", args));
        Log("  silent     : " + Silent + ", ярлыки: " + !NoIcons + ", запуск: " + !NoRun);
        Log("  папка      : " + TargetDir);
        Log("  себя       : " + SelfExe);
        Log("  temp       : " + Path.GetTempPath());
        Log("  temp доступен для записи: " + TempWritable());

        try
        {
            if (HasSwitch("DELETELATER")) return DeleteLater();
            if (HasSwitch("UNINSTALL") || HasSwitch("U") || UninstallerNameIsSelf())
            {
                Log("режим: удаление");
                return Uninstall();
            }
            Log("режим: установка");
            int code = Install();
            Log("=== готово, код " + code + " ===");
            return code;
        }
        catch (Exception ex)
        {
            Log("ОШИБКА УСТАНОВКИ: " + ex.GetType().Name + ": " + ex.Message);
            Log("  стек: " + ex.StackTrace);
            Log("  целевая папка: " + TargetDir);
            Log("  файлов в папке: " + SafeFileCount(TargetDir));
            Error("Ошибка установки", ex.Message + Environment.NewLine + Environment.NewLine +
                  "Подробности в файле: " + LogPath());
            return 1;
        }
    }

    static bool TempWritable()
    {
        try
        {
            string probe = Path.Combine(Path.GetTempPath(), "vpl_probe.tmp");
            File.WriteAllText(probe, "1");
            File.Delete(probe);
            return true;
        }
        catch { return false; }
    }

    static string SafeFileCount(string dir)
    {
        try { return Directory.Exists(dir) ? Directory.GetFiles(dir).Length.ToString() : "нет папки"; }
        catch (Exception e) { return "не читается: " + e.Message; }
    }

    static string LogPath()
    {
        try
        {
            string p = Path.Combine(Path.GetTempPath(), "vpnlauncher_setup.log");
            File.AppendAllText(p, "");
            return p;
        }
        catch
        {
            try { return Path.Combine(SelfDir, "vpnlauncher_setup.log"); }
            catch { return "(не удалось определить путь)"; }
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

    // Ключ есть в командной строке? Учитываем и форму /KEY, и /KEY=значение:
    // раньше сравнивался весь аргумент целиком, и /DELETELATER=... не
    // распознавался - помощник удаления молча уходил в режим установки
    // и висел бесконечно, ничего не удаляя.
    static bool HasSwitch(string name)
    {
        string[] args = Environment.GetCommandLineArgs();
        foreach (string raw in args)
        {
            string a = raw.Trim().Trim('"').TrimStart('/', '-');
            int eq = a.IndexOf('=');
            if (eq >= 0) a = a.Substring(0, eq);
            if (string.Equals(a, name, StringComparison.OrdinalIgnoreCase)) return true;
        }
        return false;
    }

    // значение ключа: /KEY=значение или /KEY значение
    static string SwitchValue(string name)
    {
        string[] args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length; i++)
        {
            string s = args[i].Trim().Trim('"').TrimStart('/', '-');
            int eq = s.IndexOf('=');
            string key = eq >= 0 ? s.Substring(0, eq) : s;
            if (!string.Equals(key, name, StringComparison.OrdinalIgnoreCase)) continue;
            if (eq >= 0) return s.Substring(eq + 1).Trim().Trim('"');
            if (i + 1 < args.Length) return args[i + 1].Trim().Trim('"');
            return "";
        }
        return "";
    }

    // ---------------------------------------------------------------- требования

    // Что программе реально нужно на компьютере:
    //   - Windows 10 1809 (build 17763) или новее
    //   - .NET Framework 4.6.1+ (входит в состав Windows 10/11)
    //   - PowerShell 5.1, а точнее System.Management.Automation: без него
    //     не запустится VPN.ps1, который рисует интерфейс
    //   - около 250 МБ свободного места
    // Всё это штатно есть в Windows 10 и 11, но на урезанных образах,
    // в Windows Sandbox и после неудачного обновления чего-то не хватает.
    class Prereq
    {
        public string Title;      // что не так
        public string Detail;     // почему это важно
        public string WingetId;   // что доставить через winget, null если только предупредить
        public bool Fatal;        // без этого программа не запустится
        public string HelpUrl;    // официальная страница, если winget нет
    }

    // Environment.OSVersion врёт без манифеста совместимости (отдаёт 6.2),
    // поэтому версию спрашиваем у ядра напрямую
    [StructLayout(LayoutKind.Sequential)]
    struct RTL_OSVERSIONINFOEX
    {
        public uint OSVersionInfoSize;
        public uint MajorVersion;
        public uint MinorVersion;
        public uint BuildNumber;
        public uint PlatformId;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string CSDVersion;
        public ushort ServicePackMajor;
        public ushort ServicePackMinor;
        public ushort SuiteMask;
        public byte ProductType;
        public byte Reserved;
    }

    [DllImport("ntdll.dll")]
    static extern int RtlGetVersion(ref RTL_OSVERSIONINFOEX v);

    static uint WindowsBuild()
    {
        try
        {
            RTL_OSVERSIONINFOEX v = new RTL_OSVERSIONINFOEX();
            v.OSVersionInfoSize = (uint)Marshal.SizeOf(typeof(RTL_OSVERSIONINFOEX));
            if (RtlGetVersion(ref v) == 0) return v.BuildNumber;
        }
        catch { }
        return (uint)Environment.OSVersion.Version.Build;
    }

    static bool IsWin10OrNewer()
    {
        uint build = WindowsBuild();
        Log("  сборка Windows: " + build + " (через RtlGetVersion)");
        return build >= 17763;
    }

    static int NetFxRelease()
    {
        try
        {
            using (Microsoft.Win32.RegistryKey k = Microsoft.Win32.Registry.LocalMachine
                .OpenSubKey(@"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full"))
            {
                if (k == null) return 0;
                object v = k.GetValue("Release");
                return v == null ? 0 : Convert.ToInt32(v);
            }
        }
        catch { return 0; }
    }

    // 394254 = 4.6.1, 461808 = 4.7.2, 528040 = 4.8
    static bool HasNetFx()
    {
        return NetFxRelease() >= 394254;
    }

    static bool HasPowerShell51()
    {
        // именно System.Management.Automation нужен хосту, а не powershell.exe
        try
        {
            Assembly.Load(new AssemblyName("System.Management.Automation, Version=3.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35"));
            return true;
        }
        catch { }
        try { Assembly.Load(new AssemblyName("System.Management.Automation")); return true; }
        catch { return false; }
    }

    static long FreeSpaceMB(string dir)
    {
        try
        {
            string root = Path.GetPathRoot(Path.GetFullPath(dir));
            if (string.IsNullOrEmpty(root)) return -1;
            return new DriveInfo(root).AvailableFreeSpace / (1024 * 1024);
        }
        catch { return -1; }
    }

    // При первой установке папки ещё нет, поэтому проверять запись прямо
    // в неё бессмысленно: ищем ближайшего существующего предка.
    // Раньше здесь был баг - чистая установка всегда падала с кодом 2.
    static bool CanWrite(string dir)
    {
        try
        {
            string d = Path.GetFullPath(dir);
            while (!string.IsNullOrEmpty(d) && !Directory.Exists(d))
            {
                string parent = Path.GetDirectoryName(d.TrimEnd('\\'));
                if (string.IsNullOrEmpty(parent) || parent == d) break;
                d = parent;
            }
            if (!Directory.Exists(d)) { Log("  не нашёл существующую папку для проверки прав"); return false; }

            string test = Path.Combine(d, "vpl_write_test_" + Guid.NewGuid().ToString("N").Substring(0, 6) + ".tmp");
            File.WriteAllText(test, "1");
            File.Delete(test);
            Log("  права на запись проверены в " + d);
            return true;
        }
        catch (Exception ex) { Log("  проверка прав не прошла: " + ex.Message); return false; }
    }

    static List<Prereq> CheckPrereqs(string targetDir)
    {
        var list = new List<Prereq>();
        Log("=== проверка требований ===");
        Log("  система      : Windows, сборка " + WindowsBuild());
        Log("  .NET Framework: release " + NetFxRelease());
        Log("  PowerShell 5.1: " + HasPowerShell51());
        Log("  место        : " + FreeSpaceMB(targetDir) + " МБ");

        if (!IsWin10OrNewer())
        {
            list.Add(new Prereq {
                Title = "Слишком старая версия Windows",
                Detail = "Нужна Windows 10 версии 1809 (сборка 17763) или новее. Сейчас сборка " + WindowsBuild() + ".",
                Fatal = true });
        }

        if (!HasNetFx())
        {
            list.Add(new Prereq {
                Title = "Нет .NET Framework 4.6.1 или новее",
                Detail = "Без него программа не запустится. Обычно он уже есть в Windows, но может быть удалён.",
                WingetId = "Microsoft.DotNet.Framework.4.8",
                Fatal = true,
                HelpUrl = "https://dotnet.microsoft.com/download/dotnet-framework" });
        }

        if (!HasPowerShell51())
        {
            list.Add(new Prereq {
                Title = "Нет PowerShell 5.1",
                Detail = "Программа запускает интерфейс через встроенный движок PowerShell, " +
                         "поэтому без него окно не появится. Обычно он есть в Windows 10 и 11.",
                Fatal = true,
                HelpUrl = "https://learn.microsoft.com/powershell/scripting/install/installing-powershell" });
        }

        long free = FreeSpaceMB(targetDir);
        if (free >= 0 && free < 250)
        {
            list.Add(new Prereq {
                Title = "Мало свободного места",
                Detail = "Нужно около 250 МБ, доступно " + free + " МБ. Освободи место и запусти установку снова.",
                Fatal = true });
        }

        if (!CanWrite(targetDir))
        {
            list.Add(new Prereq {
                Title = "Нет доступа к папке установки",
                Detail = "Не удалось создать файл в " + targetDir + ". Выбери другую папку или проверь права.",
                Fatal = true });
        }

        if (list.Count == 0) Log("  все требования выполнены");
        else foreach (Prereq p in list) Log("  ТРЕБУЕТ: " + p.Title);
        return list;
    }

    static bool WingetAvailable()
    {
        try
        {
            Process p = Process.Start(new ProcessStartInfo("winget", "--version") {
                UseShellExecute = false, RedirectStandardOutput = true,
                CreateNoWindow = true, RedirectStandardError = true });
            if (p == null) return false;
            string v = p.StandardOutput.ReadToEnd();
            p.WaitForExit(20000);
            return p.ExitCode == 0;
        }
        catch { return false; }
    }

    // Доставляем недостающее через winget: это официальный источник
    // Microsoft, установка идёт с UAC и пишет в свой лог.
    static string InstallWithWinget(string id)
    {
        try
        {
            Log("winget install " + id);
            ProcessStartInfo psi = new ProcessStartInfo("winget",
                "install --id " + id + " --silent --accept-package-agreements " +
                "--accept-source-agreements --disable-interactivity") {
                UseShellExecute = false, RedirectStandardOutput = true,
                RedirectStandardError = true, CreateNoWindow = true };
            Process p = Process.Start(psi);
            string outp = p.StandardOutput.ReadToEnd() + p.StandardError.ReadToEnd();
            if (!p.WaitForExit(900000))
            {
                Log("winget: превышено время ожидания");
                return "превышено время ожидания";
            }
            Log("winget: код " + p.ExitCode + ", вывод: " + outp.Trim());
            return p.ExitCode == 0 ? null : ("winget вернул код " + p.ExitCode);
        }
        catch (Exception ex) { Log("winget: " + ex.Message); return ex.Message; }
    }

    static void OpenHelp(string url)
    {
        if (string.IsNullOrEmpty(url)) return;
        try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); }
        catch { }
    }

    // Показывает пользователю, чего не хватает, и предлагает доставить.
    // Возвращает true, если можно продолжать установку.
    static bool EnsurePrereqs(string targetDir, Action<int, string> prog)
    {
        prog(0, "Проверка системы");
        List<Prereq> need = CheckPrereqs(targetDir);
        if (need.Count == 0) return true;

        bool canFix = true;
        foreach (Prereq p in need) if (p.WingetId == null) canFix = false;

        // тихая установка: решаем сами, но всё пишем в лог
        if (Silent)
        {
            if (!canFix)
            {
                foreach (Prereq p in need)
                    Log("НЕ УДАЁТСЯ УСТРАНИТЬ АВТОМАТИЧЕСКИ: " + p.Title + " - " + p.Detail);
                return false;
            }
            if (!WingetAvailable())
            {
                Log("winget недоступен, автоустановка невозможна");
                return false;
            }
            foreach (Prereq p in need)
            {
                prog(1, "Установка: " + p.Title);
                string err = InstallWithWinget(p.WingetId);
                if (err != null) { Log("не удалось поставить " + p.WingetId + ": " + err); return false; }
            }
            return CheckPrereqs(targetDir).Count == 0;
        }

        // обычный запуск: спрашиваем, молча ничего не ставим
        var sb = new StringBuilder();
        sb.AppendLine("На этом компьютере не хватает:");
        sb.AppendLine();
        foreach (Prereq p in need)
        {
            sb.AppendLine("  • " + p.Title);
            sb.AppendLine("    " + p.Detail);
        }
        sb.AppendLine();
        if (canFix && WingetAvailable())
            sb.AppendLine("Доставить сейчас через winget (официальный источник Microsoft)? " +
                          "Потребуется подтверждение в окне Windows.");
        else
        {
            sb.AppendLine("Это можно поставить вручную, ссылки откроются сами:");
            foreach (Prereq p in need)
                if (p.HelpUrl != null) sb.AppendLine("  • " + p.HelpUrl);
        }
        Log("требуется вмешательство: " + sb.ToString().Replace("\n", " | "));

        if (canFix && WingetAvailable())
        {
            DialogResult r = Ask(sb.ToString(), "Нужны дополнительные компоненты",
                                 MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
            if (r != DialogResult.Yes)
            {
                foreach (Prereq p in need) if (p.HelpUrl != null) OpenHelp(p.HelpUrl);
                return false;
            }
            foreach (Prereq p in need)
            {
                prog(1, "Установка: " + p.Title);
                string err = InstallWithWinget(p.WingetId);
                if (err != null)
                {
                    Error("Не удалось установить", p.Title + Environment.NewLine + err);
                    if (p.HelpUrl != null) OpenHelp(p.HelpUrl);
                    return false;
                }
            }
            List<Prereq> left = CheckPrereqs(targetDir);
            if (left.Count > 0)
            {
                Error("Требования не выполнены", "После установки всё ещё не хватает:" + Environment.NewLine + left[0].Title);
                return false;
            }
            return true;
        }

        MessageBox.Show(sb.ToString(), "Нужны дополнительные компоненты",
                        MessageBoxButtons.OK, MessageBoxIcon.Warning);
        foreach (Prereq p in need) if (p.HelpUrl != null) OpenHelp(p.HelpUrl);
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

        // сначала требования: ставить файлы на машину, где программа
        // всё равно не запустится, бессмысленно
        if (!EnsurePrereqs(TargetDir, prog))
        {
            Log("установка остановлена: не выполнены требования");
            return 2;
        }

        // программа может быть запущена: закрываем её до копирования файлов,
        // иначе Windows не даст заменить её собственный exe
        StopApp();

        prog(2, "Проверка предыдущей версии");
        string oldDir = RegisteredDir() ?? string.Empty;
        Log("зарегистрированная папка: " + (oldDir.Length == 0 ? "(нет)" : oldDir));
        Log("целевая папка          : " + TargetDir);
        if (!string.IsNullOrEmpty(oldDir) &&
            !string.Equals(oldDir.TrimEnd('\\'), TargetDir.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase))
        {
            Log("старая установка в другом месте, удаляю: " + oldDir);
            RemoveOldInstall(oldDir);
        }

        prog(8, "Копирование файлов");
        string tmp = Path.Combine(Path.GetTempPath(), "vpnlauncher_install_" + Guid.NewGuid().ToString("N").Substring(0, 8));
        try
        {
            Directory.CreateDirectory(tmp);
            Log("временная папка: " + tmp);
            prog(14, "Распаковка файлов программы");
            ExtractPayload(tmp, delegate(int p) { prog(14 + p * 54, "Распаковка файлов программы"); });
            Log("распаковано файлов: " + Directory.GetFiles(tmp).Length);

            prog(72, "Обновление папки программы");
            Directory.CreateDirectory(TargetDir);
            foreach (string f in Directory.GetFiles(tmp))
            {
                string dst = Path.Combine(TargetDir, Path.GetFileName(f));
                try { File.Copy(f, dst, true); }
                catch (IOException)
                {
                    Log("файл занят, освобождаю: " + Path.GetFileName(f));
                    TryReplace(dst);
                    try { File.Copy(f, dst, true); }
                    catch (Exception ex)
                    {
                        Log("НЕ УДАЛОСЬ заменить " + Path.GetFileName(f) + ": " + ex.GetType().Name + ": " + ex.Message);
                        throw;
                    }
                }
                catch (UnauthorizedAccessException ex)
                {
                    Log("НЕТ ПРАВА заменить " + Path.GetFileName(f) + ": " + ex.Message);
                    throw;
                }
            }
            Log("файлы скопированы");

            prog(78, "Проверка файлов");
            if (!File.Exists(Path.Combine(TargetDir, ExeName)))
                throw new FileNotFoundException("Не найден " + ExeName + " после копирования.");
            if (!File.Exists(Path.Combine(TargetDir, "VPN.ps1")))
                throw new FileNotFoundException("Не найден VPN.ps1 после копирования.");
            Log("проверка файлов пройдена");

            // копия установщика внутри папки программы: ею удаляют программу
            // через "Программы и компоненты", её нельзя запускать как приложение
            prog(82, "Подготовка удаления");
            string unins = Path.Combine(TargetDir, UninstallerName);
            if (!string.Equals(Path.GetFullPath(SelfExe), Path.GetFullPath(unins), StringComparison.OrdinalIgnoreCase))
            {
                Log("копирую деинсталлятор: " + unins);
                File.Copy(SelfExe, unins, true);
                Log("деинсталлятор готов, " + new FileInfo(unins).Length + " байт");
            }

            prog(88, "Создание ярлыков");
            MakeShortcuts();
            Log("ярлыки готовы");

            prog(94, "Регистрация в списке программ");
            Register();
            Log("реестр готов");

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
            try { File.Delete(path); Log("освобождён " + Path.GetFileName(path)); return; }
            catch (IOException ex)
            {
                if (i % 8 == 0) Log("занят " + Path.GetFileName(path) + ", попытка " + i + ": " + ex.Message);
                StopApp(); System.Threading.Thread.Sleep(250);
            }
            catch (UnauthorizedAccessException ex)
            {
                if (i % 8 == 0) Log("нет прав на " + Path.GetFileName(path) + ", попытка " + i + ": " + ex.Message);
                System.Threading.Thread.Sleep(250);
            }
        }
        Log("НЕ УДАЛОСЬ освободить " + path + " за 40 попыток");
    }

    static void ExtractPayload(string dest, Action<int> tick)
    {
        using (Stream s = OpenPayload())
        using (ZipArchive zip = new ZipArchive(s, ZipArchiveMode.Read))
        {
            // файл мог докачаться не полностью или повредиться при копировании:
            // сообщение должно быть понятным, а не " Unexpected end of stream"
            long total = 0;
            foreach (ZipArchiveEntry e in zip.Entries) total += e.Length;
            Log("payload: записей " + zip.Entries.Count + ", распакованный размер " + total + " байт");
            if (zip.Entries.Count == 0)
                throw new InvalidOperationException(
                    "В установщике нет файлов программы. Файл скачался с ошибкой или повреждён. " +
                    "Скачай его заново и запусти повторно.");

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
                try
                {
                    using (Stream inS = e.Open())
                    using (FileStream outS = new FileStream(outPath, FileMode.Create, FileAccess.Write, FileShare.None))
                        inS.CopyTo(outS);
                }
                catch (InvalidDataException ex)
                {
                    throw new InvalidOperationException(
                        "Файл " + e.FullName + " внутри установщика повреждён (" + ex.Message + "). " +
                        "Скорее всего, установщик скачался не полностью. Скачай его заново.", ex);
                }

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
        if (NoIcons) { Log("ярлыки пропущены (/NOICONS)"); return; }
        string target = Path.Combine(TargetDir, ExeName);
        string icon = target;

        try
        {
            MakeShortcut(Path.Combine(DesktopDir(), ShortcutName + ".lnk"), target, icon,
                         "Установленный VPN-клиент", null);
        }
        catch (Exception ex) { Log("ярлык на рабочем столе: " + ex.Message); }

        // ярлык в меню "Пуск" не должен срывать установку: на части машин
        // папка Start Menu недоступна или перенаправлена, и установщик
        // раньше падал целиком вместо того, чтобы поставить программу
        try
        {
            string menu = StartMenuDir();
            Directory.CreateDirectory(menu);
            MakeShortcut(Path.Combine(menu, ShortcutName + ".lnk"), target, icon,
                         "Установленный VPN-клиент", null);
            MakeShortcut(Path.Combine(menu, "Удалить VPN ЛАУНЧЕР.lnk"),
                         Path.Combine(TargetDir, UninstallerName), icon,
                         "Удаление программы", "/UNINSTALL");
            Log("ярлыки в меню Пуск созданы: " + menu);
        }
        catch (Exception ex)
        {
            Log("НЕ СМОГ создать ярлыки в меню Пуск (" + StartMenuDir() + "): " + ex.Message);
            Log("продолжаю установку без них, программа будет работать");
        }

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
        // ВАЖНО: возвращаем пустую строку, а не null.
        // Раньше здесь возвращался null, и вызывающий код делал oldDir.Length -
        // на машине, где программа ещё не установлена, установщик падал с
        // "Ссылка на объект не указывает на экземпляр объекта".
        try
        {
            using (Microsoft.Win32.RegistryKey k = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(UnregKey))
            {
                if (k == null) return string.Empty;
                return (k.GetValue("InstallLocation") as string) ?? string.Empty;
            }
        }
        catch { return string.Empty; }
    }

    // ---------------------------------------------------------------- удаление

    // Пользователь запускает uninstall.exe из папки программы без всяких
    // ключей. Раньше режим определялся только ключом /UNINSTALL, поэтому
    // двойной клик по uninstall.exe не удалял программу, а устанавливал
    // её заново. Теперь имя файла тоже считается командой.
    static bool UninstallerNameIsSelf()
    {
        try
        {
            string me = Path.GetFileNameWithoutExtension(SelfExe);
            return string.Equals(me, "uninstall", StringComparison.OrdinalIgnoreCase);
        }
        catch { return false; }
    }

    static int Uninstall()
    {
        Log("=== удаление ===");
        Log("  запущен из : " + SelfExe);
        Log("  ключ       : /UNINSTALL " + (UninstallerNameIsSelf() ? "(определено по имени файла)" : "(по ключу)"));

        // Удалять надо ту папку, где стоит программа, а не ту, откуда запущен
        // установщик: иначе setup.exe /UNINSTALL снёс бы сам себя с папкой dist
        string dir = SelfDir;
        if (!File.Exists(Path.Combine(dir, ExeName)))
        {
            string reg = RegisteredDir();
            if (!string.IsNullOrEmpty(reg) && File.Exists(Path.Combine(reg, ExeName))) dir = reg;
        }
        Log("  папка      : " + dir);
        if (dir != SelfDir) Log("  беру папку из реестра, а не откуда запущен");

        bool silent = Silent;
        Log("  silent     : " + silent);

        if (!silent)
        {
            DialogResult r = Ask(
                "Удалить " + ProductName + "?\r\n\r\n" +
                "Будут удалены:\r\n" +
                "  • программа из папки " + dir + "\r\n" +
                "  • ярлыки на рабочем столе и в меню «Пуск»\r\n" +
                "  • запись из «Программы и компоненты»\r\n\r\n" +
                "Внимание: вместе с папкой удалится сохранённая ссылка на подписку.\r\n" +
                "После удаления её придётся ввести заново.",
                "Удаление программы",
                MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
            if (r != DialogResult.Yes) { Log("  пользователь отказался"); return 0; }
        }

        StopApp();
        Log("  программа остановлена");
        string menu = StartMenuDir();
        try { File.Delete(Path.Combine(DesktopDir(), ShortcutName + ".lnk")); Log("  ярлык на рабочем столе удалён"); } catch { }
        try { Microsoft.Win32.Registry.CurrentUser.DeleteSubKeyTree(UnregKey, false); Log("  запись в реестре удалена"); } catch { }

        if (!Directory.Exists(dir) && !Directory.Exists(menu)) { Log("  удалять нечего"); return 0; }

        // Папку нельзя удалить, пока из неё запущен сам деинсталлятор, поэтому
        // удаляет отдельная копия нас самих из %TEMP%, уже после нашего выхода.
        //
        // Раньше это была строка cmd с rmdir в цикле, и она была порочной:
        // цикл жил ~5 секунд и успевал снести папку, если пользователь ставил
        // программу заново. Здесь всё под контролем - удаляем, пока папка
        // есть, и сразу выходим, как только её не осталось.
        string list = dir + "|" + menu;
        string helper = Path.Combine(Path.GetTempPath(),
            "vpl-remove-" + Guid.NewGuid().ToString("N").Substring(0, 8) + ".exe");
        try
        {
            File.Copy(SelfExe, helper, true);
            Process hp = new Process();
            hp.StartInfo.FileName = helper;
            hp.StartInfo.Arguments = "/DELETELATER=\"" + list + "\"";
            hp.StartInfo.UseShellExecute = false;
            hp.StartInfo.CreateNoWindow = true;
            hp.StartInfo.WindowStyle = ProcessWindowStyle.Hidden;
            hp.Start();
            Log("  удаление папок поручено помощнику " + helper);
        }
        catch (Exception ex)
        {
            Log("  не удалось запустить помощника: " + ex.Message);
            // крайний случай: пробуем удалить папку обычной командой
            try { Directory.Delete(dir, true); } catch { }
            try { if (Directory.Exists(menu)) Directory.Delete(menu, true); } catch { }
        }

        return 0;
    }

    // Запуск из временной копии деинсталлятора: ждём, пока основной процесс
    // выйдет, и сносим папки. Список папок приходит ключом /DELETELATER.
    static int DeleteLater()
    {
        string list = SwitchValue("DELETELATER");
        string self = SelfExe;
        string[] dirs = list.Split(new char[] { '|' }, StringSplitOptions.RemoveEmptyEntries);
        Log("=== помощник удаления ===");
        Log("  я        : " + self);
        Log("  папки    : " + string.Join(" ; ", dirs));

        bool left = dirs.Length > 0;
        for (int attempt = 0; attempt < 20; attempt++)
        {
            System.Threading.Thread.Sleep(500);
            left = false;
            foreach (string d in dirs)
            {
                if (!Directory.Exists(d)) continue;
                try
                {
                    Directory.Delete(d, true);
                    Log("  удалил   : " + d);
                }
                catch (Exception ex)
                {
                    left = true;
                    Log("  не смог  : " + d + "  (" + ex.GetType().Name + ")");
                }
            }
            if (!left) break;
            if (attempt == 4 || attempt == 9) Log("  ещёtry  : попытка " + (attempt + 1) + ", осталось " + (left ? "да" : "нет"));
        }
        Log("  всё удалено: " + (left ? "НЕТ" : "да"));

        // убрать за собой свою временную копию. Ждём подольше и пробуем дважды:
        // del не может удалить exe, пока он ещё выполняется
        try
        {
            Process p = new Process();
            p.StartInfo.FileName = "cmd.exe";
            p.StartInfo.Arguments = "/c \"ping -n 4 127.0.0.1 >nul & del /f /q \"" + self +
                                    "\" & ping -n 3 127.0.0.1 >nul & del /f /q \"" + self + "\"\"";
            p.StartInfo.UseShellExecute = false;
            p.StartInfo.CreateNoWindow = true;
            p.StartInfo.WindowStyle = ProcessWindowStyle.Hidden;
            p.Start();
        }
        catch { }

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
        // Раньше здесь читался p.MainModule.FileName, и на процессе с
        // повышенными правами Windows даёт "Отказано в доступе".
        // Исключение глоталось, программа оставалась жить, держала свой
        // exe, и установка обрывалась на середине. Поэтому путь читаем
        // только для информации, а Kill() делаем всегда.
        //
        // Останавливаем не только VPNLauncher, но и наш деинсталлятор,
        // если он запущен из целевой папки: он тоже держит свой файл,
        // и следующая установка падала бы с "файл используется другим
        // процессом". Себя самого не трогаем.
        int me = Process.GetCurrentProcess().Id;
        string target = "";
        try { target = new DirectoryInfo(TargetDir).FullName.TrimEnd('\\'); } catch { }

        try
        {
            foreach (string name in new string[] { "VPNLauncher", "uninstall" })
            {
                foreach (Process p in Process.GetProcessesByName(name))
                {
                    if (p.Id == me) continue;

                    string path = "?";
                    bool inTarget = false;
                    try
                    {
                        path = p.MainModule.FileName;
                        inTarget = target.Length > 0 &&
                            path.StartsWith(target, StringComparison.OrdinalIgnoreCase);
                    }
                    catch { }

                    // VPNLauncher останавливаем всегда (может быть повышенным),
                    // а uninstall.exe - только когда он лежит в целевой папке
                    if (name == "uninstall" && !inTarget) continue;

                    Log("останавливаю процесс " + name + " pid " + p.Id + " (" + path + ")");
                    try { p.CloseMainWindow(); } catch { }
                    try { p.WaitForExit(1500); } catch { }
                    if (!HasExited(p))
                    {
                        try { p.Kill(); Log("  принудительно остановлен"); }
                        catch (Exception ex) { Log("  не удалось остановить: " + ex.Message); }
                    }
                    try { p.WaitForExit(3000); } catch { }
                }
            }
        }
        catch (Exception ex) { Log("StopApp: " + ex.Message); }

        // ждём, пока Windows реально отпустит exe, иначе копирование падает
        for (int i = 0; i < 30; i++)
        {
            if (!IsAppRunning() && !IsUninstallerRunning(target, me)) return;
            System.Threading.Thread.Sleep(200);
        }
        Log("предупреждение: программа всё ещё работает после остановки");
    }

    static bool IsUninstallerRunning(string target, int me)
    {
        try
        {
            if (target.Length == 0) return false;
            foreach (Process p in Process.GetProcessesByName("uninstall"))
            {
                if (p.Id == me) continue;
                try
                {
                    if (p.HasExited) continue;
                    if (p.MainModule.FileName.StartsWith(target, StringComparison.OrdinalIgnoreCase)) return true;
                }
                catch { }
            }
            return false;
        }
        catch { return false; }
    }

    static bool HasExited(Process p)
    {
        try { return p.HasExited; } catch { return true; }
    }

    static bool IsAppRunning()
    {
        try
        {
            foreach (Process p in Process.GetProcessesByName("VPNLauncher"))
            {
                try { if (!p.HasExited) return true; } catch { }
            }
            return false;
        }
        catch { return false; }
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
                Log("RunInstall вернул " + code);
            }
            catch (Exception ex)
            {
                // раньше здесь ошибка показывалась пользователю, но не писалась
                // в лог, и причину было невозможно понять
                Log("ОШИБКА УСТАНОВКИ (окно): " + ex.GetType().Name + ": " + ex.Message);
                Log("  стек: " + ex.StackTrace);
                Error("Установка не завершена", ex.Message + Environment.NewLine + Environment.NewLine +
                      "Подробности в файле: " + LogPath());
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
        // в тихой установке диалог показывать нельзя: его никто не увидит,
        // а установка (например из SFX-обёртки) навсегда зависнет
        if (Silent) return;
        MessageBox.Show(text, title, MessageBoxButtons.OK, MessageBoxIcon.Error);
    }

    static void Log(string msg)
    {
        string stamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
        try
        {
            File.AppendAllText(LogPath(), stamp + " " + msg + Environment.NewLine);
        }
        catch { }
        try
        {
            // запасной лог рядом с установщиком, если temp недоступен
            string alt = Path.Combine(SelfDir, "vpnlauncher_setup.log");
            if (!string.Equals(Path.GetFullPath(alt), Path.GetFullPath(LogPath()), StringComparison.OrdinalIgnoreCase))
                File.AppendAllText(alt, stamp + " " + msg + Environment.NewLine);
        }
        catch { }
    }
}
