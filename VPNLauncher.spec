# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onedir-сборка VPN LAUNCHER (Python edition).
#
# Запуск: build-app.ps1 (версия, sing-box.exe рядом с exe, portable zip).
# Вручную: venv\Scripts\pyinstaller.exe --clean VPNLauncher.spec
#
# Раскладка: dist\VPNLauncher\VPNLauncher.exe + _internal\ (Python, PySide6).
# sing-box.exe НЕ входит в spec - его кладёт build-app.ps1 рядом с exe,
# потому что paths.install_root() в frozen-режиме = папка самого exe.
import os
import tempfile
from pathlib import Path

import PySide6
from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPEC).resolve().parent
VERSION = os.environ.get("VPN_VERSION", "2.1.0")

# 13.10.2026: HTML-интерфейс (QtWebEngine) тянет за собой процесс Chromium и
# ресурсы Qt - собираем их явно; ассеты страницы кладутся в <_MEIPASS>/assets,
# их ищет vpn_launcher.ui.web.window.assets_dir().
datas = []
binaries = []
hiddenimports = []
for _pkg in (
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel",
):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

_WEB_ASSETS = ROOT / "vpn_launcher" / "ui" / "web" / "assets"
datas.append((str(_WEB_ASSETS), "assets"))
_qwc = Path(PySide6.__file__).resolve().parent / "QtWebChannel" / "qwebchannel.js"
if _qwc.exists():
    datas.append((str(_qwc), "assets"))


def _keep_data(src: str) -> bool:
    """Режем ballast: чужие языки (52 МБ), QML (24 МБ) и DevTools (83 МБ)."""
    low = str(src).replace("/", "\\").lower()
    name = Path(low).name
    if name.startswith("qtwebengine_devtools"):
        return False  # отладчик в релизной программе не открывается
    if "\\translations\\" in low:
        return name.startswith(("qtbase_", "qtwebchannel_")) and (
            name.endswith("_ru.qm") or name.endswith("_en.qm")
        )
    return "\\qml\\" not in low


datas = [d for d in datas if _keep_data(d[0])]

# версия exe: шаблон с плейсхолдерами -> временный файл для PyInstaller
_tpl = (ROOT / "installer" / "version_info.txt").read_text(encoding="utf-8")
_ver4 = ".".join((VERSION.split(".") + ["0", "0", "0"])[:4])
_ver_tuple = "(" + ", ".join(_ver4.split(".")) + ")"
_vfile = Path(tempfile.mkdtemp(prefix="vpnver_")) / "version_info.txt"
_vfile.write_text(
    _tpl.replace("VERSION_STR", VERSION).replace("VERSION_TUPLE", _ver_tuple),
    encoding="utf-8",
)

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

# те же правила - для файлов, которые подтянул хук PySide6
a.datas = [entry for entry in a.datas if _keep_data(entry[0])]

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VPNLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # без консоли: окно, а не чёрный экран (как 1.0.6 exe)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "installer" / "app.ico"),
    version=str(_vfile),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VPNLauncher",
)
