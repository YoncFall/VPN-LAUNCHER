// Host.cs - нативная оболочка VPN ЛАУНЧЕР.
// GUI работает внутри этого процесса: в панели задач и в Alt+Tab своя иконка,
// окно консоли не создаётся, процесса powershell.exe в диспетчере задач нет.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Management.Automation;
using System.Management.Automation.Runspaces;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

static class Host
{
    const string MutexName = @"Local\MyVPNLauncher_YoncFALL_9E1F4C";
    const int SW_RESTORE = 9;

    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr l);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "GetWindowTextW")]
    static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "GetClassNameW")]
    static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
    delegate bool EnumProc(IntPtr h, IntPtr l);

    static string AppDir = "";
    static string PidFile = "";
    static bool PidFileMine = false;

    [STAThread]
    static int Main(string[] args)
    {
        AppDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        try { Environment.CurrentDirectory = AppDir; } catch { }
        PidFile = Path.Combine(AppDir, "app.pid");

        if (HasFlag(args, "--selftest")) { return SelfTest(); }

        string script = FindScript();
        if (script == null)
        {
            ShowError("Не найден файл VPN.ps1",
                      "Ожидался файл VPN.ps1 рядом с программой или в папке src.\r\n\r\nПапка программы:\r\n" + AppDir);
            return 2;
        }

        bool created;
        using (Mutex mutex = new Mutex(true, MutexName, out created))
        {
            if (!created)
            {
                FocusExisting();
                return 0;
            }
            try
            {
                MarkPid();
                TryBoostPriority();
                return RunScript(script, HasFlag(args, "--autoconnect"));
            }
            catch (Exception ex)
            {
                Log("FATAL: " + ex);
                ShowError("Ошибка запуска", ex.Message);
                return 1;
            }
            finally
            {
                ClearPid();
                try { mutex.ReleaseMutex(); } catch { }
            }
        }
    }

    // Скрипт читается в память и выполняется прямо в этом процессе.
    // Так политика выполнения сценариев Windows не применяется к файлу,
    // а окно принадлежит нашему процессу, а не powershell.exe.
    static int RunScript(string scriptPath, bool autoconnect)
    {
        string text = Prepare(File.ReadAllText(scriptPath, Encoding.UTF8));
        using (PowerShell ps = PowerShell.Create())
        {
            ps.AddScript(text);
            if (autoconnect) ps.AddParameter("Autoconnect");
            ps.Invoke();

            if (ps.HadErrors)
            {
                StringBuilder sb = new StringBuilder();
                foreach (ErrorRecord er in ps.Streams.Error)
                {
                    Log("PS ERROR: " + er);
                    if (sb.Length < 1800) sb.AppendLine(er.ToString());
                }
                ShowError("Ошибка в VPN.ps1", sb.ToString().Trim());
                return 3;
            }
        }
        return 0;
    }

    // У сценария, загруженного из памяти, $PSScriptRoot всегда пустой, а сессионную
    // переменную перебивает автоматическая. Поэтому подставляем путь прямо в текст.
    // Подстановка идёт после блока param, поэтому параметры скрипта не ломаются.
    static string Prepare(string text)
    {
        string root = "'" + AppDir.Replace("'", "''") + "'";
        if (text.IndexOf("$PSScriptRoot", StringComparison.Ordinal) >= 0)
        {
            text = text.Replace("$PSScriptRoot", root);
            Log("корень подстанован в скрипт: " + AppDir);
        }
        return text;
    }

    static int SelfTest()
    {
        try
        {
            string outFile = Path.Combine(AppDir, "selftest.txt");
            string probe = Prepare(
                "$PSVersionTable.PSVersion.ToString() + '|' + " +
                "[System.Diagnostics.Process]::GetCurrentProcess().ProcessName + '|' + $PSScriptRoot + '|' + " +
                "(Test-Path (Join-Path $PSScriptRoot 'app.ico'))");
            using (PowerShell ps = PowerShell.Create())
            {
                ps.AddScript(probe);
                var res = ps.Invoke();
                if (ps.HadErrors || res.Count == 0) { Log("SELFTEST: движок не ответил"); return 9; }
                File.WriteAllText(outFile, res[0].ToString(), new UTF8Encoding(false));
            }
            return 0;
        }
        catch (Exception ex) { Log("SELFTEST FAIL: " + ex); return 9; }
    }

    static bool HasFlag(string[] args, string name)
    {
        if (args == null) return false;
        foreach (string a in args)
            if (string.Equals(a, name, StringComparison.OrdinalIgnoreCase)) return true;
        return false;
    }

    static string FindScript()
    {
        string[] candidates = {
            Path.Combine(AppDir, "VPN.ps1"),
            Path.Combine(AppDir, "src", "VPN.ps1"),
            Path.Combine(Path.GetDirectoryName(AppDir.TrimEnd('\\')) ?? AppDir, "VPN.ps1"),
        };
        foreach (string c in candidates)
            if (File.Exists(c)) return c;
        return null;
    }

    static void MarkPid()
    {
        try { File.WriteAllText(PidFile, Process.GetCurrentProcess().Id.ToString(), new UTF8Encoding(false)); PidFileMine = true; }
        catch (Exception ex) { Log("pid-файл: " + ex.Message); }
    }

    static void ClearPid()
    {
        if (!PidFileMine) return;
        try { File.Delete(PidFile); } catch { }
    }

    static int ExistingPid()
    {
        try
        {
            string s = File.ReadAllText(PidFile).Trim();
            int id;
            if (int.TryParse(s, out id))
            {
                Process p = Process.GetProcessById(id);
                if (!p.HasExited) return id;
            }
        }
        catch { }
        return 0;
    }

    // Повторный запуск не открывает второе окно, а выводит уже запущенное.
    static void FocusExisting()
    {
        IntPtr h = IntPtr.Zero;
        int pid = ExistingPid();
        if (pid > 0)
        {
            foreach (IntPtr w in TopLevelWindows())
            {
                uint p;
                GetWindowThreadProcessId(w, out p);
                if (p == (uint)pid && LooksLikeApp(w)) { h = w; break; }
            }
        }
        if (h == IntPtr.Zero)
            foreach (IntPtr w in TopLevelWindows())
                if (LooksLikeApp(w)) { h = w; break; }

        if (h == IntPtr.Zero) return;
        ShowWindow(h, SW_RESTORE);
        uint dummy;
        uint fgThread = GetWindowThreadProcessId(GetForegroundWindow(), out dummy);
        uint me = GetCurrentThreadId();
        AttachThreadInput(me, fgThread, true);
        SetForegroundWindow(h);
        AttachThreadInput(me, fgThread, false);
    }

    static bool LooksLikeApp(IntPtr h)
    {
        if (!IsWindowVisible(h)) return false;
        var cls = new StringBuilder(256);
        GetClassNameW(h, cls, 256);
        if (cls.ToString().IndexOf("WindowsForms", StringComparison.OrdinalIgnoreCase) < 0) return false;
        var txt = new StringBuilder(256);
        GetWindowTextW(h, txt, 256);
        return txt.Length > 0;
    }

    static List<IntPtr> TopLevelWindows()
    {
        var list = new List<IntPtr>();
        EnumWindows(delegate(IntPtr h, IntPtr l) { if (IsWindow(h)) list.Add(h); return true; }, IntPtr.Zero);
        return list;
    }

    static void TryBoostPriority()
    {
        try { Process.GetCurrentProcess().PriorityClass = ProcessPriorityClass.High; } catch { }
    }

    static void Log(string msg)
    {
        try
        {
            File.AppendAllText(Path.Combine(AppDir, "host.log"),
                DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " " + msg + Environment.NewLine,
                new UTF8Encoding(false));
        }
        catch { }
    }

    static void ShowError(string title, string text)
    {
        try
        {
            MessageBoxIcon icon = MessageBoxIcon.Error;
            if (title.IndexOf("установ", StringComparison.OrdinalIgnoreCase) >= 0) icon = MessageBoxIcon.Information;
            MessageBox.Show(text, title, MessageBoxButtons.OK, icon);
        }
        catch { }
    }
}
