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

ROOT = Path(SPEC).resolve().parent
VERSION = os.environ.get("VPN_VERSION", "2.1.0")

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
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

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
