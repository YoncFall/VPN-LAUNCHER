# -*- coding: utf-8 -*-
# pytest: корень проекта попадает в sys.path, `import vpn_launcher` работает из tests/.
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from vpn_launcher.paths import SING_BOX


def _discover_sing_box() -> Path | None:
    """Движок для `sing-box check`: env SING_BOX_EXE -> paths.SING_BOX -> dev-кэш Temp."""
    env = os.environ.get("SING_BOX_EXE")
    if env and Path(env).is_file():
        return Path(env)
    if SING_BOX.is_file():
        return SING_BOX
    # dev-раскладка: движок лежит в Temp\opencode\singbox\<версия>\
    root = Path(tempfile.gettempdir()) / "opencode" / "singbox"
    if root.is_dir():
        hits = sorted(root.rglob("sing-box.exe"))
        if hits:
            return hits[-1]
    return None


@pytest.fixture
def sing_box_exe() -> Path:
    """Путь к sing-box.exe; пропускает тест, если движок не найден."""
    exe = _discover_sing_box()
    if exe is None:
        pytest.skip("sing-box.exe не найден (задайте SING_BOX_EXE)")
    return exe
