using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

// Обёртка запуска для VPN LAUNCHER BY @YoncFALL.
// Собрана как WinExe, поэтому окно консоли не создаётся вообще.
// GUI рисует VPN.ps1, этот файл только поднимает PowerShell без окна
// и следит, чтобы копия была одна.

internal static class Program
{
    private const string WindowTitle = "VPN ЛАУНЧЕР BY @YoncFALL";
    private const string MutexName = "Local\\MyVPNLauncher_YoncFALL_9E1F4C";
    private const int ErrorAlreadyExists = 183;

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateMutex(IntPtr mutexAttributes, bool initialOwner, string name);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr FindWindow(string className, string windowName);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBoxW(IntPtr hWnd, string text, string caption, uint type);

    [STAThread]
    private static int Main(string[] args)
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;

        string script = Path.Combine(dir, "VPN.ps1");
        if (!File.Exists(script))
        {
            script = Path.Combine(Path.Combine(dir, "src"), "VPN.ps1");
        }
        if (!File.Exists(script))
        {
            Fail("Файл VPN.ps1 не найден." + Environment.NewLine + "Ожидаемая папка:" + Environment.NewLine + dir);
            return 2;
        }

        string workDir = Path.GetDirectoryName(script);

        IntPtr mutex = CreateMutex(IntPtr.Zero, true, MutexName);
        if (Marshal.GetLastWin32Error() == ErrorAlreadyExists)
        {
            // вторая копия: поднимаем уже открытое окно вместо нового
            IntPtr existing = FindWindow(null, WindowTitle);
            if (existing != IntPtr.Zero)
            {
                ShowWindow(existing, 9);
                SetForegroundWindow(existing);
            }
            return 0;
        }

        string shell = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.System),
            @"WindowsPowerShell\v1.0\powershell.exe");
        if (!File.Exists(shell))
        {
            shell = "powershell.exe";
        }

        ProcessStartInfo psi = new ProcessStartInfo();
        psi.FileName = shell;
        psi.Arguments = "-NoProfile -NoLogo -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File \"" + script + "\"";
        psi.WorkingDirectory = workDir;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.WindowStyle = ProcessWindowStyle.Hidden;

        try
        {
            using (Process child = Process.Start(psi))
            {
                child.WaitForExit();
                GC.KeepAlive(mutex);
                return child.ExitCode;
            }
        }
        catch (Exception ex)
        {
            Fail("Не удалось запустить PowerShell." + Environment.NewLine + ex.Message);
            return 3;
        }
    }

    // своя реализация MessageBox, чтобы не тянуть System.Windows.Forms
    private static void Fail(string text)
    {
        MessageBoxW(IntPtr.Zero, text, WindowTitle, 0x10);
    }
}
