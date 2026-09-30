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

    def test_setup_spare_log_only_when_temp_fails(self):
        """Отклонение: запасной лог у setup.exe не мусорит там, откуда его запустили.

        1.0.6 писал его всегда (файл оставался на рабочем столе/в загрузках).
        """
        cs = _read("installer/Setup.cs")
        assert "if (written != null) return;" in cs


class TestSetupSideBySide:
    """Установка второй копией рядом с работающей (30.09.2026).

    Раньше StopApp гасил ЛЮБОЙ процесс VPNLauncher, включая копию из чужой
    папки: установка новой версии убивала работающую старую. Kill() обрывает
    её подключение и оставляет сирот kill switch и sing-box - убрать их умеет
    только корректное закрытие самого приложения. Теперь лаунчер
    останавливается лишь когда свой exe уже стоит в целевой папке
    (обновление/удаление); первая установка чужие копии не трогает.
    """

    def test_launcher_stopped_only_when_own_exe_in_target(self):
        cs = _read("installer/Setup.cs")
        # решает наличие своего exe, а не путь процесса: для повышенного
        # процесса MainModule недоступен, и старая проверка врала бы
        assert "File.Exists(Path.Combine(target, ExeName))" in cs
        assert "if (!ownExeInTarget) continue;" in cs

    def test_wait_loop_ignores_foreign_launcher(self):
        # иначе первая установка провисала бы на 6 секунд с ложным
        # предупреждением "программа всё ещё работает после остановки"
        cs = _read("installer/Setup.cs")
        assert "IsAppRunning(ownExeInTarget)" in cs
        assert "static bool IsAppRunning(bool ownExeInTarget)" in cs

    def test_uninstall_aims_stopapp_at_real_install_dir(self):
        # TargetDir по умолчанию - DefaultDir(): установка в нестандартную
        # папку иначе не гасит свой же exe и не удаляется
        cs = _read("installer/Setup.cs")
        assert "TargetDir = dir;" in cs

    def test_foreign_copy_is_never_killed_on_fresh_install(self):
        cs = _read("installer/Setup.cs")
        # ветка гашения лаунчера обязана идти раньше безусловного Kill
        i_gate = cs.index("if (!ownExeInTarget) continue;")
        i_kill = cs.index('Log("останавливаю процесс " + name')
        assert i_gate < i_kill


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

    def test_app_script_builds_to_given_distpath(self):
        # сборка в обход занятого dist\VPNLauncher (локальный exe запущен)
        s = _read("build-app.ps1")
        assert "[string]$DistPath" in s
        assert "--distpath" in s

    def test_app_script_zip_excludes_runtime_files(self):
        # portable zip не должен нести state.json с личной ссылкой подписки
        s = _read("build-app.ps1")
        for f in ("state.json", "config.json", "vpn-launcher.log", "cache.db"):
            assert f"'{f}'" in s, f

    def test_installer_script_accepts_appdist(self):
        s = _read("build-installer.ps1")
        assert "[string]$AppDist" in s  # установщик из произвольной сборки


class TestFrozenPaths:
    def test_install_root_frozen_is_exe_dir(self, tmp_path, monkeypatch):
        """Установленная раскладка: данные лежат рядом с VPNLauncher.exe."""
        import vpn_launcher.paths as paths

        exe = tmp_path / "VPNLauncher.exe"
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe))
        assert paths.install_root() == tmp_path.resolve()
