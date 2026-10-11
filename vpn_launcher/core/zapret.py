# -*- coding: utf-8 -*-
"""Обход блокировок (zapret/winws): движок, стратегии, автоподбор.

2.2.0 (просьба 02.10): кнопка в лаунчере сама подбирает рабочую стратегию
обхода DPI. winws запускается с одной из 22 стратегий (zapret_presets),
проверяются реальные сайты (Discord/YouTube), первая сработавшая
сохраняется в state['zapretStrategy'] и остаётся работать.

Файлы движка лежат в <корень>/zapret/ (подкаталоги bin: winws.exe,
WinDivert, полезные грузы .bin; lists: списки целей). Это второй движок
рядом с sing-box: запуск/остановка НЕ трогает VPN-часть.

Дисциплина процессов: управляется ТОЛЬКО свой winws (свой Popen,
terminate только ему). Чужие экземпляры winws (например, репак с
рабочего стола или его служба) не гасятся - пока они живы, подбор
отказывается работать (двойной перехват портил бы результаты пробы).
"""
from __future__ import annotations

import subprocess
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from vpn_launcher.core.log import write_log
from vpn_launcher.core.zapret_presets import PRESETS
from vpn_launcher.paths import install_root

ZAPRET_DIR = install_root() / "zapret"
WINWS = ZAPRET_DIR / "bin" / "winws.exe"
BIN_DIR = ZAPRET_DIR / "bin"
LISTS_DIR = ZAPRET_DIR / "lists"

# Пробы - DATA-запросы (HTTP GET с ответом), а не TCP-хендшейк: с заглушкой
# соединения хендшейк «успевает» и даёт ложное «работает» (та же история,
# что с auto-catcher v2 для winws).
PROBE_URLS = (
    "https://discord.com/api/gateway",
    "https://gateway.discord.gg/api/gateway",
    "https://www.youtube.com",
)
PROBE_TIMEOUT = 6.0
WARMUP = 1.3  # окно старта winws: подхват WinDivert и поднятие фильтров

_CREATE_NO_WINDOW = 0x08000000


def preset_names() -> list[str]:
    return [p["name"] for p in PRESETS]


def build_args(name: str) -> list[str]:
    """Аргументы winws для стратегии (подстановка {BIN} и {LISTS})."""
    for p in PRESETS:
        if p["name"] == name:
            bin_prefix = str(BIN_DIR) + "\\"
            lists_prefix = str(LISTS_DIR) + "\\"
            return [
                a.replace("{BIN}", bin_prefix).replace("{LISTS}", lists_prefix)
                for a in p["args"]
            ]
    raise KeyError(name)


def probe(urls: tuple[str, ...] = PROBE_URLS, timeout: float = PROBE_TIMEOUT) -> bool:
    """True - все узлы отвечают данными (HTTP < 500 за отведённое время)."""
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status >= 500:
                    return False
        except Exception as exc:
            write_log(f"zapret probe: {url} -> {exc.__class__.__name__}")
            return False
    return True


def foreign_winws_running(own_pid: int | None = None) -> bool:
    """Жив ли winws, НЕ запущенный нами (tasklist по имени образа)."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq winws.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_CREATE_NO_WINDOW,
        ).stdout
    except Exception:
        return False
    for line in out.splitlines():
        if "winws.exe" not in line.lower():
            continue
        parts = line.split()
        try:
            pid = int(parts[1])
        except (IndexError, ValueError):
            continue
        if own_pid is None or pid != own_pid:
            return True
    return False


class ZapretController:
    """Запуск/остановка СВОЕГО winws. Чужие процессы не трогаем."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None

    @property
    def pid(self) -> int | None:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc.pid
        return None

    def running(self) -> bool:
        return self.pid is not None

    def start(self, name: str) -> None:
        """Запустить стратегию (предыдущий свой экземпляр - остановить)."""
        if self.running():
            self.stop()
        args = [str(WINWS), *build_args(name)]
        write_log(f"zapret: start strategy '{name}' ({len(args) - 1} args)")
        # вывод winws (ошибки запуска без --debug печатаются именно туда)
        # перенаправляем в файл - иначе он теряется без консоли
        log_path = ZAPRET_DIR / "winws.log"
        try:
            logf = open(log_path, "w", encoding="utf-8", errors="replace")
        except OSError:
            logf = None
        try:
            self._proc = subprocess.Popen(
                args, cwd=str(BIN_DIR), creationflags=_CREATE_NO_WINDOW,
                stdout=logf, stderr=logf,
            )
        finally:
            if logf is not None:
                logf.close()
        time.sleep(0.35)  # мгновенный крэш/ошибка аргументов - фиксируем
        rc = self._proc.poll()
        if rc is not None:
            write_log(
                f"zapret: winws '{name}' exited immediately (code {rc})"
            )

    def stop(self) -> None:
        """Остановить СВОЙ winws (сиротой при закрытии окна не оставляем)."""
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
            write_log("zapret: stopped (own winws)")
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=5)
                write_log("zapret: stopped by kill (own winws)")
            except Exception as exc:
                write_log(f"zapret: stop ERROR {exc}")


def run_autotest(
    controller: ZapretController,
    probe_fn: Callable[[], bool] | None = None,
    progress: Callable[[str], None] | None = None,
    warmup: float = WARMUP,
) -> tuple[str | None, str]:
    """Подбор рабочей стратегии. -> (имя | None, сообщение для статуса).

    Порядок: чужой winws -> отказ; блокировок нет -> general (базовая);
    иначе - первая стратегия, после которой пробы проходят. При успехе
    выигравшая стратегия ОСТАЁТСЯ запущенной (controller не останавливается).
    """
    probe_fn = probe_fn or probe
    if foreign_winws_running():
        write_log("zapret: foreign winws running - autotest aborted")
        return None, "Запущен другой обход (winws) - закрой его и повтори"

    if probe_fn():
        # блокировок не видно (или они уже сняты) - базовая стратегия
        write_log("zapret: baseline probe passed, no blocks visible")
        try:
            controller.start("general")
        except OSError as exc:
            return None, f"Не удалось запустить winws: {exc}"
        return "general", "Блокировок не обнаружено - оставляю general"

    write_log("zapret: blocks detected, iterating strategies")
    total = len(PRESETS)
    for i, preset in enumerate(PRESETS, 1):
        if progress:
            progress(f"Подбор обхода: {i}/{total} ({preset['name']})...")
        try:
            controller.start(preset["name"])
        except OSError as exc:
            write_log(f"zapret: start failed for {preset['name']}: {exc}")
            continue
        time.sleep(warmup)
        if probe_fn():
            write_log(f"zapret: winner '{preset['name']}' ({i}/{total})")
            return preset["name"], f"Рабочая стратегия: {preset['name']} ({i}/{total})"
        write_log(f"zapret: '{preset['name']}' did not unblock")
        controller.stop()
    write_log("zapret: no strategy worked")
    return None, "Ни одна стратегия не помогла - проверь интернет"
