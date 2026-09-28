# -*- coding: utf-8 -*-
"""Тесты Windows-мостов (этап 2): autostart, elevate, mutex, proc."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from vpn_launcher.paths import install_root
from vpn_launcher.win import autostart, elevate, mutex, proc

_REPO = Path(__file__).resolve().parents[1]


# ---------------- autostart (изолированный фейковый winreg) ----------------


class _FakeKey:
    def __init__(self, reg: "_FakeReg", path: str):
        self._reg = reg
        self._path = path

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def SetValueEx(self, name, _reserved, _typ, value):
        self._reg.store.setdefault(self._path, {})[name] = value

    def QueryValueEx(self, name):
        if name not in self._reg.store.get(self._path, {}):
            raise FileNotFoundError(name)  # как winreg при отсутствии значения
        return self._reg.store[self._path][name], 1

    def DeleteValue(self, name):
        if name not in self._reg.store.get(self._path, {}):
            raise FileNotFoundError(name)  # как winreg.DeleteValue
        del self._reg.store[self._path][name]


class _FakeReg:
    HKEY_CURRENT_USER = 0
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.store: dict[str, dict[str, str]] = {}

    def OpenKey(self, _hive, path, _res=0, _access=0):
        return _FakeKey(self, path)

    # winreg.QueryValueEx/DeleteValue/SetValueEx - функции модуля, принимающие ключ
    def QueryValueEx(self, key, name):
        return key.QueryValueEx(name)

    def DeleteValue(self, key, name):
        key.DeleteValue(name)

    def SetValueEx(self, key, name, reserved, typ, value):
        key.SetValueEx(name, reserved, typ, value)


@pytest.fixture
def fake_autostart(monkeypatch):
    reg = _FakeReg()
    logs: list[str] = []
    monkeypatch.setattr(autostart, "winreg", reg)
    monkeypatch.setattr(autostart, "write_log", logs.append)
    return reg, logs


class TestAutostart:
    def test_disabled_by_default(self, fake_autostart):
        assert autostart.is_autostart_enabled() is False

    def test_enable_writes_command_and_logs(self, fake_autostart):
        reg, logs = fake_autostart
        autostart.set_autostart(True)
        assert autostart.is_autostart_enabled() is True
        command = reg.store[autostart._KEY][autostart.RUN_VALUE_NAME]
        assert command.startswith('"')
        assert logs == [f"autostart ON: {command}"]

    def test_disable_removes_value(self, fake_autostart):
        reg, logs = fake_autostart
        autostart.set_autostart(True)
        autostart.set_autostart(False)
        assert autostart.is_autostart_enabled() is False
        assert autostart.RUN_VALUE_NAME not in reg.store.get(autostart._KEY, {})
        assert logs[-1] == "autostart OFF"  # перед этим был лог ON от set(True)

    def test_disable_when_absent_is_silent_noop(self, fake_autostart):
        _reg, logs = fake_autostart
        autostart.set_autostart(False)
        assert logs == []

    def test_empty_value_counts_as_disabled(self, fake_autostart):
        reg, _logs = fake_autostart
        reg.store[autostart._KEY] = {autostart.RUN_VALUE_NAME: ""}
        assert autostart.is_autostart_enabled() is False


# ---------------- elevate ----------------


class TestElevate:
    def test_is_elevated_returns_bool(self):
        assert isinstance(elevate.is_elevated(), bool)

    def _patch(self, monkeypatch, rc: int = 33):
        calls: list[tuple[str, str]] = []
        logs: list[str] = []

        def fake_shell_execute(exe: str, params: str) -> int:
            calls.append((exe, params))
            return rc

        monkeypatch.setattr(elevate, "_shell_execute", fake_shell_execute)
        monkeypatch.setattr(elevate, "write_log", logs.append)
        return calls, logs

    def test_relaunch_dev_uses_python_host(self, monkeypatch):
        calls, logs = self._patch(monkeypatch)
        elevate.relaunch_elevated(["--autoconnect"])
        exe, params = calls[0]
        assert exe == sys.executable
        assert '"--autoconnect"' in params
        assert "falling back to python host" in logs[0]  # аналог PS powershell-fallback

    def test_relaunch_frozen_elevates_own_exe(self, monkeypatch):
        calls, logs = self._patch(monkeypatch)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        elevate.relaunch_elevated(["--autoconnect"])
        exe, params = calls[0]
        assert exe == sys.executable
        assert params == '"--autoconnect"'  # без скрипта - только аргументы
        assert logs[0] == f"elevating own executable: {exe}"

    def test_failure_raises_and_logs(self, monkeypatch):
        _calls, logs = self._patch(monkeypatch, rc=5)
        with pytest.raises(OSError, match="rc=5"):
            elevate.relaunch_elevated([])
        assert any(m.startswith("elevation ERROR:") for m in logs)

    def test_uac_cancel_reported(self, monkeypatch):
        _calls, _logs = self._patch(monkeypatch, rc=1223)
        with pytest.raises(OSError, match="UAC cancelled"):
            elevate.relaunch_elevated([])


# ---------------- mutex ----------------


class TestMutex:
    def test_names_match_host_cs(self):
        # Host.cs:17-18; разные имена обязательны для TUN-перезапуска (Host.cs:59-61)
        assert mutex.MUTEX_NAME == r"Local\MyVPNLauncher_YoncFALL_9E1F4C"
        assert mutex.MUTEX_NAME_ELEVATED == r"Local\MyVPNLauncher_YoncFALL_9E1F4C_Elevated"

    def test_mutex_name_depends_on_elevation(self, monkeypatch):
        monkeypatch.setattr(mutex.elevate, "is_elevated", lambda: False)
        assert mutex._mutex_name() == mutex.MUTEX_NAME
        monkeypatch.setattr(mutex.elevate, "is_elevated", lambda: True)
        assert mutex._mutex_name() == mutex.MUTEX_NAME_ELEVATED

    def test_other_process_blocks_and_release_allows(self):
        """Ключевая семантика Host.cs: чужой процесс -> False, после выхода -> True.

        Порядок важен: до этого теста в сессии мьютекс никто не брал.
        """
        child_src = textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, {str(_REPO)!r})
            from vpn_launcher.win.mutex import acquire_instance
            print("ACQUIRED" if acquire_instance() else "BLOCKED", flush=True)
            time.sleep(60)
        """)
        child = subprocess.Popen(
            [sys.executable, "-c", child_src],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            line = child.stdout.readline().strip()
            if line != "ACQUIRED":
                child.wait(timeout=5)
                pytest.fail(f"дочерний процесс не взял мьютекс: {line!r} {child.stderr.read()!r}")
            assert mutex.acquire_instance() is False  # второй экземпляр
        finally:
            child.terminate()
            child.wait(timeout=10)
        time.sleep(0.1)  # ядро освобождает объект при завершении процесса
        assert mutex.acquire_instance() is True  # экземпляр наш
        # владелец пишет app.pid (Host.cs MarkPid)
        pid_path = install_root() / mutex.PID_FILE_NAME
        assert pid_path.read_text(encoding="utf-8").strip() == str(os.getpid())

    def test_acquire_is_idempotent_inside_process(self):
        assert mutex.acquire_instance() is True
        assert mutex.acquire_instance() is True  # хэндл уже наш (см. докстринг)

    def test_window_helpers_degrade_gracefully(self):
        assert mutex._looks_like_app(0) is False
        assert mutex._window_pid(0) == 0
        assert mutex.focus_window(0) is None  # no-op вместо падения


# ---------------- proc ----------------


class TestProc:
    def test_running_exe_list_basic(self):
        items = proc.get_running_exe_list()
        assert items, "список запущенных процессов пуст"
        assert "python.exe" in items  # pytest запущен из python.exe
        assert "idle.exe" in items    # PID 0: паритет с Get-RunningExeList (PS)

    def test_running_exe_list_sorted_and_unique(self):
        items = proc.get_running_exe_list()
        folds = [x.casefold() for x in items]
        assert len(folds) == len(set(folds))  # PS `-notin` регистронезависим
        assert folds == sorted(folds)          # PS Sort-Object
        assert all(x for x in items)

    def test_start_stop_stay_stage5(self):
        with pytest.raises(NotImplementedError):
            proc.start_sing_box("config.json")
        with pytest.raises(NotImplementedError):
            proc.stop_sing_box()
