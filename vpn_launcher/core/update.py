# -*- coding: utf-8 -*-
"""Проверка новой версии на сайте (apps.json) и подготовка обновления.

Источник версий - apps.json на GitHub Pages: он обновляется при каждом
релизе (тот же файл, что показывает версии на сайте) и не имеет
rate-limit'ов GitHub API (общие exit-IP VPN делили бы лимит на всех).
Логика разбора/сравнения отделена от сети: fetch подменяется в тестах.

Сценарии применения (Windows):
  - установленная копия (рядом uninstall.exe): скачиваем Setup.exe во
    временную папку; helper-скрипт ждёт нашего полного выхода и только
    потом запускает установщик - наш closeEvent успевает снять kill
    switch и sing-box/winws, установщик не борется с занятыми файлами;
  - portable (zip) и dev-запуск: открываем страницу релиза в браузере
    (самостоятельная замена файлов под работающим exe ненадёжна).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

APPS_JSON_URL = "https://yoncfall.github.io/apps.json"
SLUG = "vpn-launcher"  # slug Windows-приложения на сайте
HTTP_TIMEOUT_S = 8
CHUNK = 1 << 20  # 1 MiB - шаг чтения при скачивании

_VERSION_RE = re.compile(r"\d+")


def parse_version(text: str) -> tuple[int, ...]:
    """'v2.3.10' -> (2, 3, 10); нечисловые хвосты игнорируются."""
    return tuple(int(p) for p in _VERSION_RE.findall(str(text)))


def is_newer(latest: str, current: str) -> bool:
    """True, если latest строго новее current (сравнение по числам, не строкам)."""
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


@dataclass(frozen=True)
class UpdateInfo:
    """Найденная новая версия."""

    version: str
    download: str  # Setup.exe (установленная копия)
    download_zip: str  # portable zip
    release_page: str


def pick_app(payload: dict, slug: str) -> dict | None:
    """Найти приложение по slug в apps.json (categories[].apps[])."""
    for cat in payload.get("categories", []):
        for app in cat.get("apps", []):
            if app.get("slug") == slug:
                return app
    return None


def parse_latest(payload_text: str, slug: str, current: str) -> UpdateInfo | None:
    """Разобрать apps.json; UpdateInfo только если там версия новее current.

    Ведущий UTF-8 BOM срезается: PowerShell `Set-Content -Encoding UTF8`
    пишет файл с BOM, а json.loads на нём кидает ValueError - из-за этого
    апдейтер молча не увидел обновление 2.4.2 (инцидент 31.10.2026).
    """
    try:
        payload = json.loads(str(payload_text).lstrip("\ufeff"))
    except (ValueError, TypeError):
        return None
    app = pick_app(payload, slug)
    if not app:
        return None
    latest = str(app.get("version") or "")
    if not latest or not is_newer(latest, current):
        return None
    return UpdateInfo(
        version=latest,
        download=str(app.get("download") or ""),
        download_zip=str(app.get("downloadZip") or ""),
        release_page=str(app.get("releasePage") or ""),
    )


def fetch_latest(
    slug: str = SLUG,
    current: str = "",
    *,
    url: str = APPS_JSON_URL,
    timeout: float = HTTP_TIMEOUT_S,
) -> UpdateInfo | None:
    """Скачать apps.json и вернуть UpdateInfo или None (в т.ч. при ошибке сети).

    Тихий отказ - офлайн при запуске не должен показывать плашку об ошибке.
    """
    req = urllib.request.Request(  # noqa: S310 - фиксированный https-URL сайта
        url, headers={"User-Agent": f"VPN-LAUNCHER/{current or '0'}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            text = resp.read().decode("utf-8", "replace")
    except OSError:
        return None
    return parse_latest(text, slug, current)


def download_file(
    url: str,
    dest: Path,
    *,
    progress=None,
    timeout: float = HTTP_TIMEOUT_S,
) -> Path:
    """Потоковое скачивание в dest; progress(loaded, total|None) по мегабайтам."""
    req = urllib.request.Request(url, headers={"User-Agent": "VPN-LAUNCHER"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        total = resp.headers.get("Content-Length")
        total_b = int(total) if total and total.isdigit() else None
        done = 0
        with open(dest, "wb") as fh:
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total_b)
    return dest


def is_installed_copy() -> bool:
    """Установленная копия (Setup.exe) vs portable zip vs dev-запуск.

    uninstall.exe создаёт установщик рядом с exe (Setup.cs: File.Copy(SelfExe,
    unins)); в portable zip его нет, в dev-запуске sys.frozen выключен.
    """
    if not getattr(sys, "frozen", False):
        return False
    from vpn_launcher.paths import install_root

    return (install_root() / "uninstall.exe").is_file()


def setup_dest(version: str) -> Path:
    """Куда качать Setup.exe: %TEMP%\\VPN-LAUNCHER-Setup-<ver>.exe."""
    import tempfile

    return Path(tempfile.gettempdir()) / f"VPN-LAUNCHER-Setup-{version}.exe"


def helper_script(
    setup_path: Path,
    app_path: Path,
    target_version: str = "",
    install_dir: Path | str | None = None,
) -> str:
    """PowerShell-скрипт: дождаться нашего выхода, тихо установить, запустить.

    /S - тихий режим установщика. После установки приложение запускается
    само (в тихом режиме Setup.cs этого не делает).

    2.4.9: helper передаёт /DIR=<папка установки>. Без него Setup.exe ставит
    обновление в папку по умолчанию (%LOCALAPPDATA%\\Programs\\VPNLauncher),
    а при нестандартном пути ещё и удаляет прежнюю установку - обновление
    «переезжало» и теряло state.json.

    2.4.8: helper работает без единого окна. Он ждёт смены версии (в том
    числе когда установщик перезапустился с правами и вернул код 4), при
    неудаче пишет короткий файл с причиной и всё равно запускает программу.
    Ни блокнота, ни MessageBox: пользователь видит только, что программа
    закрылась и снова открылась.

    Скрипт пишется в UTF-8 с BOM: Windows PowerShell 5.1 иначе читает
    русский текст как мусор.
    """
    return (
        "param([int]$WaitPid, [string]$Setup, [string]$App, [string]$TargetVer,"
        " [string]$Lock, [string]$Dir)\n"
        "$ErrorActionPreference = 'SilentlyContinue'\n"
        "try { Wait-Process -Id $WaitPid -Timeout 300 -ErrorAction Stop } catch {}\n"
        "function Get-Ver([string]$p) {\n"
        "  try { return [string](Get-Item -LiteralPath $p).VersionInfo.FileVersion }"
        " catch { return '' }\n"
        "}\n"
        "# /DIR= ставит обновление в ту же папку, где лежит работающая копия\n"
        "# (2.4.9). Кавычки внутри аргумента: Start-Process не экранирует\n"
        "# пробелы в путях сам.\n"
        "$sa = @('/S')\n"
        "if ($Dir) { $sa += '/DIR=\"' + $Dir + '\"' }\n"
        "$p = Start-Process -FilePath $Setup -ArgumentList $sa -PassThru\n"
        "try { $null = $p.WaitForExit(600000) } catch {}\n"
        "$code = ''\n"
        "try { $code = [string]$p.ExitCode } catch {}\n"
        "# Код 4: установщик перезапустился с правами и работает отдельным\n"
        "# процессом. Ждём, пока он закончит и версия файла сменится; иначе\n"
        "# человек остался бы без программы на все 4 минуты.\n"
        "$procName = [IO.Path]::GetFileNameWithoutExtension($Setup)\n"
        "$deadline = (Get-Date).AddMinutes(4)\n"
        "$ok = $false\n"
        "if ($TargetVer) {\n"
        "  while ((Get-Date) -lt $deadline) {\n"
        "    if ((Get-Ver $App) -like ($TargetVer + '*')) { $ok = $true; break }\n"
        "    $busy = @(Get-Process -Name $procName"
        " -ErrorAction SilentlyContinue).Count -gt 0\n"
        "    if (-not $busy) {\n"
        "      # установщик больше не работает: даём Windows пару секунд\n"
        "      Start-Sleep -Seconds 2\n"
        "      if ((Get-Ver $App) -like ($TargetVer + '*')) { $ok = $true }\n"
        "      break\n"
        "    }\n"
        "    Start-Sleep -Milliseconds 400\n"
        "  }\n"
        "}\n"
        "$now = Get-Ver $App\n"
        "# 2.4.9: код установщика тоже важен. Раньше при занятом файле\n"
        "# (zapret\\bin\\cygwin1.dll держал winws) Setup успевал заменить\n"
        "# VPNLauncher.exe и падал: версия уже новая, ошибка скрыта.\n"
        "$failed = $false\n"
        "if ($TargetVer) {\n"
        "  if (-not $ok) { $failed = $true }\n"
        "  elseif ($code -and $code -ne '0' -and $code -ne '4') { $failed = $true }\n"
        "}\n"
        "if ($failed) {\n"
        "  $log = Join-Path $env:TEMP 'vpnlauncher_setup.log'\n"
        "  $err = Join-Path $env:TEMP 'vpnlauncher_update_error.txt'\n"
        "  $tail = ''\n"
        "  try { $tail = ((Get-Content -LiteralPath $log -Tail 12 -Encoding UTF8)"
        " -join [Environment]::NewLine) } catch {}\n"
        "  $text = 'Обновление не установилось.' + [Environment]::NewLine +"
        " 'Установлена версия: ' + $now + [Environment]::NewLine +"
        " 'Нужна версия: ' + $TargetVer + [Environment]::NewLine +"
        " 'Код установщика: ' + $code + [Environment]::NewLine +"
        " 'Журнал: ' + $log + [Environment]::NewLine +"
        " [Environment]::NewLine + $tail\n"
        "  try { [IO.File]::WriteAllText($err, $text,"
        " (New-Object Text.UTF8Encoding($false))) } catch {}\n"
        "}\n"
        "try { if ($Lock) { Remove-Item -LiteralPath $Lock -Force } } catch {}\n"
        "Start-Process -FilePath $App\n"
    )


def write_helper(
    dest: Path,
    setup_path: Path,
    app_path: Path,
    target_version: str = "",
    install_dir: Path | str | None = None,
) -> Path:
    """Записать helper-скрипт рядом со Setup.exe и вернуть его путь."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        helper_script(setup_path, app_path, target_version, install_dir),
        encoding="utf-8-sig",
    )
    return dest


def launch_helper(
    script: Path,
    setup_path: Path,
    app_path: Path,
    target_version: str = "",
    lock_path: Path | None = None,
    install_dir: Path | str | None = None,
) -> None:
    """Запустить helper отвязанно, без единого видимого окна.

    CREATE_NO_WINDOW обязателен: -WindowStyle Hidden у powershell.exe всё
    равно мелькает консолью, и пользователь может закрыть её вместе с
    обновлением (инцидент 19.11.2026).
    """
    import subprocess

    args = [
        "powershell.exe",
        "-NoProfile",
        "-WindowStyle",
        "Hidden",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-WaitPid",
        str(os.getpid()),
        "-Setup",
        str(setup_path),
        "-App",
        str(app_path),
        "-TargetVer",
        str(target_version),
    ]
    if lock_path is not None:
        args += ["-Lock", str(lock_path)]
    if install_dir:
        args += ["-Dir", str(install_dir)]
    kwargs: dict[str, object] = {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP,
    }
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000  # CREATE_NO_WINDOW
        )
    subprocess.Popen(args, **kwargs)  # noqa: S603 - фиксированные аргументы


# ---- блокировка на время обновления (2.4.8) --------------------------------
# Пока установщик копирует файлы, ручной запуск старой копии ломает установку
# (файл занят). lock-файл в папке программы заставляет новый запуск подождать.

UPDATE_LOCK_MAX_AGE = 600.0  # старше 10 минут - считается протухшим
UPDATE_ERROR_FILE = "vpnlauncher_update_error.txt"


def update_lock_path() -> Path:
    from vpn_launcher.paths import install_root

    return install_root() / "update.lock"


def write_update_lock(version: str) -> Path:
    """Отметить, что идёт установка версии version."""
    path = update_lock_path()
    payload = {
        "version": str(version),
        "pid": os.getpid(),
        "ts": time.time(),
    }
    try:
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass
    return path


def read_update_lock() -> dict | None:
    """Активная блокировка обновления или None (нет/протухла/битая)."""
    try:
        raw = update_lock_path().read_text(encoding="utf-8")
        info = json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict):
        return None
    try:
        age = time.time() - float(info.get("ts") or 0)
    except (TypeError, ValueError):
        return None
    if age < 0 or age > UPDATE_LOCK_MAX_AGE:
        return None
    return info


def clear_update_lock() -> None:
    try:
        update_lock_path().unlink()
    except OSError:
        pass


def update_error_path() -> Path:
    import tempfile

    return Path(tempfile.gettempdir()) / UPDATE_ERROR_FILE


def take_update_error() -> str:
    """Забрать короткий текст ошибки обновления (и удалить файл)."""
    path = update_error_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    try:
        path.unlink()
    except OSError:
        pass
    return text.strip()
