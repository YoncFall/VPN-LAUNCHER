# -*- coding: utf-8 -*-
"""Этап 6: структура сборки и установщика (без запуска PyInstaller/csc).

Сверяет согласованность spec/скриптов/Setup.cs: имя exe, версии, состав
payload, ASCII-правило для .ps1 и frozen-ветку paths.install_root().
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _version() -> str:
    m = re.search(r'__version__\s*=\s*"(\d+\.\d+\.\d+)', _read("vpn_launcher/__init__.py"))
    assert m, "cannot parse version from vpn_launcher/__init__.py"
    return m.group(1)


class TestSpec:
    def test_spec_names_exe_and_entry(self):
        spec = _read("VPNLauncher.spec")
        assert 'name="VPNLauncher"' in spec
        assert "console=False" in spec  # без консоли, как GUI exe 1.0.6
        assert 'ROOT / "app.py"' in spec
        assert 'ROOT / "installer" / "app.ico"' in spec

    def test_spec_stamps_version_from_env(self):
        spec = _read("VPNLauncher.spec")
        assert 'os.environ.get("VPN_VERSION"' in spec
        tpl = _read("installer/version_info.txt")
        assert "VERSION_STR" in tpl and "VERSION_TUPLE" in tpl


class TestInstallerAssets:
    def test_files_present(self):
        for rel in (
            "installer/Setup.cs",
            "installer/app.ico",
            "installer/app.manifest",
            "installer/version_info.txt",
            "LICENSE",
            "NOTICE.md",
        ):
            assert (ROOT / rel).is_file(), rel

    def test_setup_exe_name(self):
        cs = _read("installer/Setup.cs")
        assert 'const string ExeName = "VPNLauncher.exe";' in cs
        assert 'UninstallerName = "uninstall.exe"' in cs

    def test_setup_version_matches_app(self):
        cs = _read("installer/Setup.cs")
        assert f'const string Version = "{_version()}";' in cs

    def test_setup_py_edition_adaptations(self):
        """Адаптации Setup.cs под Python-издание (см. docstring Setup.cs)."""
        cs = _read("installer/Setup.cs")
        assert "static void CopyTree" in cs  # onedir: копируем дерево, не только верх
        assert "HasPowerShell51" not in cs  # PowerShell программе не нужен
        assert "Не найден sing-box.exe" in cs  # проверка после копирования
        assert "VPN.ps1" not in cs  # PS-версии здесь больше нет


class TestBuildScripts:
    def test_scripts_are_ascii(self):
        # правило репо: .ps1 только ASCII (PowerShell 5.1 ломает чтение)
        for rel in ("build-app.ps1", "build-installer.ps1", "run.ps1", "tools/make_golden.ps1"):
            data = (ROOT / rel).read_bytes()
            assert max(data) < 128, f"{rel}: non-ASCII bytes"

    def test_installer_script_packs_payload(self):
        s = _read("build-installer.ps1")
        assert "/resource:$payload,payload.zip" in s
        assert "Setup.cs" in s
        assert "app.manifest" in s
        assert "VPNLauncher.spec" in s or "build-app.ps1" in s  # сборка приложения отдельно
        # runtime-файлы локального прогона не должны попасть пользователям
        for f in ("state.json", "vpn-launcher.log", "cache.db"):
            assert f"'{f}'" in s, f

    def test_app_script_copies_engine_next_to_exe(self):
        s = _read("build-app.ps1")
        assert "sing-box.exe" in s  # движок рядом с exe - frozen install_root
        assert "VPNLauncher.spec" in s


class TestFrozenPaths:
    def test_install_root_frozen_is_exe_dir(self, tmp_path, monkeypatch):
        """Установленная раскладка: данные лежат рядом с VPNLauncher.exe."""
        import vpn_launcher.paths as paths

        exe = tmp_path / "VPNLauncher.exe"
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe))
        assert paths.install_root() == tmp_path.resolve()
