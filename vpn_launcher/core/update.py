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
    """Разобрать apps.json; UpdateInfo только если там версия новее current."""
    try:
        payload = json.loads(payload_text)
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


def helper_script(setup_path: Path) -> str:
    """PowerShell-скрипт: ждать выхода нашего процесса, затем запустить установщик.

    ASCII-тело, пути - параметры (Unicode на командной строке PowerShell не
    ломается, в отличие от кодировки самого .ps1).
    """
    return (
        "param([int]$WaitPid, [string]$Setup)\n"
        "$ErrorActionPreference = 'SilentlyContinue'\n"
        "try { Wait-Process -Id $WaitPid -Timeout 300 -ErrorAction Stop } catch {}\n"
        "Start-Process -FilePath $Setup\n"
    )


def write_helper(dest: Path, setup_path: Path) -> Path:
    """Записать helper-скрипт рядом со Setup.exe и вернуть его путь."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(helper_script(setup_path), encoding="ascii")
    return dest


def launch_helper(script: Path, setup_path: Path) -> None:
    """Запустить helper отвязанно (скрытое окно, переживает наш выход)."""
    import subprocess

    subprocess.Popen(  # noqa: S603 - фиксированные аргументы
        [
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
        ],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,  # noqa: S603
    )
