# -*- coding: utf-8 -*-
"""Проверка ВСЕХ стратегий winws через --dry-run (dev-tool).

winws --dry-run сверяет параметры и выходит с кодом 0, НЕ требуя ни
админ-прав, ни драйвера, ни трафика. Скрипт гоняет каждую стратегию из
core.zapret_presets и падает (exit 1), если хоть одна не прошла.

Запуск из корня репозитория:

    python tools/zapret/dry_run.py

Замечание: запуск идёт через .bat-обёртку - cygwin-бинарники в этой
среде отказываются стартовать напрямую из PowerShell-хоста, а cmd/Python
их запускают нормально; на результат влияют только коды выхода.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vpn_launcher.core.zapret import WINWS, build_args  # noqa: E402
from vpn_launcher.core.zapret_presets import PRESETS  # noqa: E402


def _dry_run(name: str, workdir: Path) -> tuple[int, str]:
    args = [str(WINWS), *build_args(name), "--dry-run"]
    quoted = " ".join('"%s"' % a if " " in a else a for a in args)
    bat = workdir / "run.bat"
    out = workdir / "out.txt"
    bat.write_text('@echo off\r\n%s > "%s" 2>&1\r\n' % (quoted, out),
                   encoding="ascii", newline="")
    r = subprocess.run(["cmd", "/c", str(bat)], cwd=str(WINWS.parent),
                       timeout=60)
    text = out.read_text(encoding="utf-8", errors="replace") if out.exists() \
        else ""
    return r.returncode, text


def main() -> int:
    failed = 0
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for preset in PRESETS:
            code, text = _dry_run(preset["name"], work)
            ok = code == 0
            print("%-14s %s" % (preset["name"], "OK" if ok else "FAIL(%d)" % code))
            if not ok:
                failed += 1
                print("   " + text.strip()[:400].replace("\n", "\n   "))
    print("failed: %d / %d" % (failed, len(PRESETS)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
