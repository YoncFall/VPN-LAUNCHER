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
рабочего стола или его служба) по умолчанию не гасятся - пока они
живы, подбор отказывается работать (двойной перехват портил бы
результаты пробы). Исключение - явное согласие пользователя в диалоге
(13.10): осиротевший winws держит тот же фильтр, и без его завершения
наш экземпляр вообще не встаёт (см. kill_foreign_winws).
"""
from __future__ import annotations

import socket
import ssl
import subprocess
import time
import urllib.parse
from collections.abc import Callable

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
# youtube первым: стабильный дискриминатор (без обхода режется всегда),
# а discord/gateway мигают - бесполезная стратегия отсеивается быстро.
# cdn/media обязана участвовать: без cdn.discordapp.com не грузится сама
# страница Discord (диагностика 12.10: под комбо discord.com и шлюз жили,
# а cdn/media оставались мертвыми - и Discord не работал при «зелёной» пробе).
PROBE_URLS = (
    "https://www.youtube.com",
    "https://discord.com/api/gateway",
    "https://cdn.discordapp.com/",
    "https://gateway.discord.gg/api/gateway",
    "https://media.discordapp.net/",
)
PROBE_TIMEOUT = 6.0
_PROBE_ATTEMPTS = 3  # повтор на URL: сеть «мигает» (anycast-IP блокируются
# избирательно, discord-адреса мигают в ~20% прогонов - диагностика 12.10),
# но стабильная недоступность (youtube без обхода) не проходит ни при
# скольких попытках. Бесполезная стратегия отсеивается быстро: первый URL
# (youtube) убит стабильно - проба возвращается после его попыток.
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


_MAX_IPS = 3  # сколько IP пробуем на один URL (ротация как у браузера)


def _fetch(url: str, timeout: float) -> int:
    """GET по URL со сменой IP при сбое (как это делает браузер).

    anycast-IP одного хоста может блокироваться избирательно: хендшейк
    упал на первом IP - пробуем следующие. urllib так не умеет (он
    привязывается к первому соединившемуся IP), из-за чего проба
    «падала» там, где браузер спокойно работает.
    -> HTTP-код ответа; исключение - транспорт не дотянулся ни до одного IP.
    """
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    ips: list[str] = []
    for fam, _st, _pr, _cn, sa in infos:
        if fam == socket.AF_INET and sa[0] not in ips:
            ips.append(sa[0])
    req = (
        f"GET {target} HTTP/1.1\r\nHost: {host}\r\n"
        "User-Agent: Mozilla/5.0\r\nConnection: close\r\n\r\n"
    ).encode("ascii")
    last: Exception | None = None
    for ip in ips[:_MAX_IPS]:
        try:
            ctx = ssl.create_default_context()
            per_ip = min(timeout, 3.0)
            with socket.create_connection((ip, port), timeout=per_ip) as raw:
                with ctx.wrap_socket(raw, server_hostname=host) as tls_s:
                    tls_s.sendall(req)
                    data = b""
                    while len(data) < 16:
                        chunk = tls_s.recv(64)
                        if not chunk:
                            break
                        data += chunk
            fields = data.split()
            if len(fields) < 2 or not fields[0].startswith(b"HTTP/"):
                raise OSError("bad http response")
            return int(fields[1])
        except Exception as exc:
            last = exc
    if last is None:
        raise OSError("no addresses for " + host)
    raise last


def probe(urls: tuple[str, ...] = PROBE_URLS, timeout: float = PROBE_TIMEOUT) -> bool:
    """True - узлы отвечают данными.

    Любой HTTP-ответ (в т.ч. 404) доказывает проходимость трафика - это
    успех, а не недоступность (урл шлюза Discord всегда отдаёт 404, но
    urllib кидает на 4xx HTTPError). Недоступность - только сбой транспорта
    (таймаут/RST) либо ответ 5xx. Каждый URL пробуем до _PROBE_ATTEMPTS
    раз: диагностика 12.10 показала, что даже рабочие стратегии мигали на
    одном адресе из трёх - единичный мёртвый прогон не должен обваливать
    стратегию.
    """
    for url in urls:
        last: Exception | None = None
        for attempt in range(_PROBE_ATTEMPTS):
            if attempt:
                time.sleep(1.0)
            try:
                code = _fetch(url, timeout)
            except Exception as exc:
                last = exc
                continue
            if code >= 500:
                last = OSError(f"HTTP {code}")
                continue
            break
        else:
            reason = getattr(last, "reason", None) or last
            write_log(f"zapret probe: {url} -> {type(last).__name__}: {reason!r}")
            return False
    return True


def _winws_pids() -> list[int]:
    """PID всех живых winws.exe (tasklist по имени образа)."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq winws.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_CREATE_NO_WINDOW,
        ).stdout
    except Exception:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        if "winws.exe" not in line.lower():
            continue
        parts = line.split()
        try:
            pids.append(int(parts[1]))
        except (IndexError, ValueError):
            continue
    return pids


def foreign_winws_running(own_pid: int | None = None) -> bool:
    """Жив ли winws, НЕ запущенный нами."""
    return any(pid != own_pid for pid in _winws_pids())


def kill_foreign_winws(own_pid: int | None = None) -> None:
    """Завершить ЧУЖИЕ экземпляры winws (своего не трогаем).

    Нужно, когда осиротевший winws (остался после аварийного закрытия
    приложения) держит тот же сетевой фильтр: с ним наш экземпляр не
    встаёт - winws пишет «A copy of winws is already running with the
    same filter» и падает с кодом 1. Вызывается ТОЛЬКО после явного
    подтверждения пользователя (диалог в _zapret_click), требует
    админ-прав.
    """
    for pid in _winws_pids():
        if pid == own_pid:
            continue
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=15,
                creationflags=_CREATE_NO_WINDOW,
            )
        except Exception:
            continue
        write_log(f"zapret: foreign winws pid {pid} terminated on user request")


def _winws_tail() -> str:
    """Последняя строка winws.log - там причина мгновенного падения."""
    try:
        lines = [
            ln.strip()
            for ln in (ZAPRET_DIR / "winws.log")
            .read_text(encoding="utf-8", errors="replace")
            .splitlines()
            if ln.strip()
        ]
    except OSError:
        return ""
    return lines[-1] if lines else ""


class ZapretController:
    """Запуск/остановка СВОЕГО winws. Чужие процессы не трогаем."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        # причина последнего неудачного старта (последняя строка winws.log)
        self.last_error: str = ""

    @property
    def pid(self) -> int | None:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc.pid
        return None

    def running(self) -> bool:
        return self.pid is not None

    def start(self, name: str) -> bool:
        """Запустить стратегию (предыдущий свой экземпляр - остановить).

        Возвращает False, если winws упал сразу (причина - в last_error:
        последняя строка winws.log, например «A copy of winws is already
        running with the same filter») - иначе сбой был бы невидим.
        """
        self.last_error = ""
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
            self.last_error = (
                _winws_tail() or f"winws завершился сразу (код {rc})"
            )
            return False
        return True

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

    Порядок: чужой winws -> отказ; блокировок нет -> combo (PRESETS[0],
    базовая); иначе - первая стратегия, после которой пробы проходят. При
    успехе выигравшая стратегия ОСТАЁТСЯ запущенной (controller не останавливается).
    """
    probe_fn = probe_fn or probe
    if foreign_winws_running():
        write_log("zapret: foreign winws running - autotest aborted")
        return None, "Запущен другой обход (winws) - закрой его и повтори"

    if probe_fn():
        # блокировок не видно (или они уже сняты) - базовая стратегия
        write_log("zapret: baseline probe passed, no blocks visible")
        name = PRESETS[0]["name"]
        try:
            controller.start(name)
        except OSError as exc:
            return None, f"Не удалось запустить winws: {exc}"
        return name, f"Блокировок не обнаружено - оставляю {name}"

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
