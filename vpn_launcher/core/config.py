# -*- coding: utf-8 -*-
"""Генерация и проверка конфига sing-box. Порт src/core.ps1, строки 457-626.

Источник:
    $GameSafeProcesses   (core.ps1:457) -> GAME_SAFE_PROCESSES
    New-SingBoxConfig    (core.ps1:466) -> build_sing_box_config (чистая сборка)
                        + new_sing_box_config (дословно: сборка + запись файла + лог)
    Test-SingBoxConfig   (core.ps1:620) -> test_sing_box_config

Правило этапа 1: вывод обязан быть эквивалентен PowerShell-версии
(golden-файлы в tests/golden/ + прогон `sing-box check`).

Отклонения от 1.0.6 (сознательные):
  - New-SingBoxConfig в PS пишет файл и возвращает путь; здесь чистая
    сборка (build_sing_box_config, для golden-тестов) отделена от записи
    (new_sing_box_config = сборка + write_config + log, как в PS);
  - JSON пишется Python json.dumps (4 пробела, UTF-8 без BOM) вместо
    ConvertTo-Json; семантически идентично, sing-box принимает оба;
  - test_sing_box_config: stderr декодируется UTF-8 (в PS 5.1 Get-Content
    читал бы ANSI) - текст ошибки может отличаться, код совпадает;
  - сравнение тегов в only_selected регистрозависимое, как PS `-contains`;
  - адрес TUN-инбаунда подбирается из свободных на этой машине вместо
    зашитого 172.19.0.1/30 (см. win/tunaddr): занятый чужим VPN адрес ронял
    sing-box на старте. Пул начинается с того же адреса - при отсутствии
    конфликтов вывод совпадает с 1.0.6 (golden-файлы не переписывали);
  - strict_route=false и route_address=["0.0.0.0/1", ...] вместо
    strict_route=true + авто-default (см. комментарий у tun-инбаунда):
    strict_route убивал DNS на время работы туннеля (WFP режет порт 53 вне
    туннеля), а default 0.0.0.0/0 чужого VPN (Happ, метрика 0) перехватывал
    системный трафик. Golden-файлы остаются эталоном PS 1.0.6 - отклонение
    нормализуется в tests/test_golden.py (_ps_parity_view);
  - app_mode="include" (30.09.2026, новая фича, не порт PS): список
    процессов работает зеркально - через VPN идут ТОЛЬКО перечисленные,
    всё остальное идёт напрямую (route.final = direct). PS 1.0.6 такого
    режима не знал, поэтому паритет касается только app_mode="exclude"
    (дефолт) - golden-файлы не переписывали.

Как режимы переключаются и как kill switch следует за режимом (02.10.2026):
    в TUN весь (не-локальный) трафик захватывают маршруты /1 и уходит в
    sing-box; там правило по process_name решает, direct это или прокси.
    Единственная точка выхода - сам движок. Kill switch (wfp.py) обязан
    управлять ровно теми же процессами, что и это правило (routed_app_processes):
      - exclude: классика - глобальная блокировка всего прямого выхода,
        но образы «мимо VPN» (игры + список) разрешены и при падении
        движка продолжают работать (остальные - fail-closed);
      - include: инверсия - глобальной блокировки нет, блокируются ТОЛЬКО
        выбранные образы: при обрыве туннеля они не утекают на прямую,
        а все остальные приложения работают напрямую без ограничений.
    Инвертировать режим можно и внутри конфига (правило и route.final),
    и в фильтрах WFP - оба места читают один и тот же список.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

from vpn_launcher.core.log import write_log
from vpn_launcher.paths import CONFIG_FILE, SOCKS_PORT, SING_BOX
from vpn_launcher.paths import install_root as _default_install_root
from vpn_launcher.win.tunaddr import choose_tun_addresses

# Процессы, которые ВСЕГДА идут напрямую, минуя туннель.
# Игры и античиты не должны видеть подмену маршрута/адреса, а Steam и EAC/BE
# не должны получать соединения из-за VPN. Список нельзя потерять - он в коде.
GAME_SAFE_PROCESSES: tuple[str, ...] = (
    "steam.exe", "steamwebhelper.exe", "steamservice.exe", "steamerrorreporter.exe", "gameoverlayui64.exe",
    "RustClient.exe", "Rust.exe", "UnityCrashHandler64.exe",
    "EasyAntiCheat.exe", "EasyAntiCheat_EOS.exe", "EasyAntiCheat_Setup.exe", "EACLauncher.exe",
    "DayZ_x64.exe", "DayZDiag_x64.exe", "DayZLauncher.exe", "DayZ_BE.exe", "BEService_x64.exe", "DayZServer_x64.exe",
    "Phasmophobia.exe", "REPO.exe", "ONCE_HUMAN.exe",
    "GTA5.exe", "GTA5_3258.exe", "ragemp_v.exe", "cs2.exe",
)

DEFAULT_TEST_URL = "https://www.gstatic.com/generate_204"

# Режимы работы списка процессов (см. docstring модуля):
#   exclude - классика PS 1.0.6: перечисленные идут мимо VPN, остальное через;
#   include - зеркало: через VPN идут только перечисленные, остальное напрямую.
APP_MODE_EXCLUDE = "exclude"
APP_MODE_INCLUDE = "include"
APP_MODES = (APP_MODE_EXCLUDE, APP_MODE_INCLUDE)

# Ключи ноды, переносимые в outbound как есть (core.ps1:486)
_NODE_KEYS = (
    "uuid", "password", "method", "alter_id", "flow", "plugin", "plugin_opts",
    "congestion_control", "tls", "transport", "obfs",
)

# Локальные сети идут напрямую (core.ps1:536)
_LOCAL_CIDRS = (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "224.0.0.0/4", "fe80::/10", "fc00::/7",
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class ConfigError(RuntimeError):
    """PS `throw` из New-SingBoxConfig."""


def _uniq(items: Iterable[str]) -> list[str]:
    """Select-Object -Unique (core.ps1:523): регистрозависимо, первый выигрывает."""
    out: list[str] = []
    for x in items:
        if x and x not in out:
            out.append(x)
    return out


def _routed_apps(app_mode: str, app_list: Sequence[str]) -> list[str]:
    """Процессы правила per-app для текущего режима списка.

    exclude: GAME_SAFE + выбор пользователя (все перечисленные -> direct);
    include: только выбор пользователя (только они -> proxy-group). Базовый
    список игр/античитов в include не участвует - там они и так идут
    напрямую (final=direct), а пользователь вправе выбрать Steam осознанно.
    """
    if app_mode == APP_MODE_INCLUDE:
        return _uniq(list(app_list))
    return _uniq(list(GAME_SAFE_PROCESSES) + list(app_list))


def routed_app_processes(app_mode: str, app_list: Sequence[str]) -> list[str]:
    """Публичный доступ к тому же списку, что и в правиле маршрутизации.

    Один источник правды: kill switch (win/wfp.py) должен блокировать
    (include) или разрешать мимо блокировки (exclude) ровно те процессы,
    которые перечислены в rules sing-box, иначе семантика режима и
    fail-closed расходятся между конфигом и WFP.
    """
    return _routed_apps(app_mode, app_list)


def build_sing_box_config(
    nodes: Sequence[dict],
    selected: Sequence[str] = (),
    mode: str = "tun",
    app_list: Sequence[str] = (),
    test_url: str = DEFAULT_TEST_URL,
    only_selected: bool = False,
    app_mode: str = APP_MODE_EXCLUDE,
    *,
    install_root: Path | str | None = None,
) -> dict[str, Any]:
    """New-SingBoxConfig без записи файла -> dict конфига (для golden-тестов).

    install_root - корень для cache.db (по умолчанию paths.install_root(),
    как $script:InstallRoot в PS); для тестов можно передать фиктивный путь.
    app_mode - режим списка процессов (APP_MODES); дефолт паритетен с PS 1.0.6.
    """
    if mode not in ("tun", "proxy"):
        raise ConfigError(f"Неизвестный режим: {mode!r} (ожидается 'tun' или 'proxy')")
    if app_mode not in APP_MODES:
        raise ConfigError(
            f"Неизвестный режим списка процессов: {app_mode!r} "
            f"(ожидается 'exclude' или 'include')"
        )

    out: list[dict[str, Any]] = []
    tags: list[str] = []

    pool: Sequence[dict] = nodes
    if only_selected and selected:
        # как PS `-contains` (регистронезависимо)
        sel = {s.casefold() for s in selected}
        pool = [n for n in nodes if str(n["tag"]).casefold() in sel]

    for n in pool:
        o: dict[str, Any] = {
            "type": n["type"], "tag": n["tag"],
            "server": n["server"], "server_port": n["server_port"],
        }
        for k in _NODE_KEYS:
            if k in n and n[k] is not None:
                o[k] = n[k]
        out.append(o)
        tags.append(n["tag"])

    # direct для процесса самого sing-box и служебных адресов
    out.append({"type": "direct", "tag": "direct"})

    # группа выбора
    use_tags = list(selected) if selected else tags
    if len(use_tags) > 1:
        out.append({
            "type": "urltest",
            "tag": "proxy-group",
            "outbounds": use_tags,
            "url": test_url,
            "interval": "10m",
            "tolerance": 50,
            "interrupt_exist_connections": True,
        })
    elif len(use_tags) == 1:
        out.append({
            "type": "selector",
            "tag": "proxy-group",
            "outbounds": [use_tags[0]],
            "default": use_tags[0],
            "interrupt_exist_connections": True,
        })
    else:
        raise ConfigError("Нет ни одного сервера")

    # маршрутизация
    rules: list[dict[str, Any]] = [{"action": "sniff"}, {"protocol": "dns", "action": "hijack-dns"}]

    # per-app: один список, два направления (см. докстринг модуля).
    #   exclude - перечисленные идут НАПРЯМУЮ (важно для игр/античита),
    #             всё прочее собирает route.final=proxy-group, т.е. через VPN;
    #   include - наоборот: только перечисленные уходят в proxy-group,
    #             route.final=direct, поэтому остальное идёт мимо VPN.
    # Правило строится только в TUN - в системном прокси источник процесса
    # неизвестен (как и раньше: см. test_proxy_inbounds_and_socks_port).
    # action обязателен с sing-box 1.11, outbound внутри правила помечен deprecated
    final = "proxy-group"
    if mode == "tun":
        routed_apps = _routed_apps(app_mode, app_list)
        if routed_apps:
            rules.append({
                "action": "route",
                "process_name": routed_apps,
                "outbound": "direct" if app_mode == APP_MODE_EXCLUDE else "proxy-group",
            })
        if app_mode == APP_MODE_INCLUDE:
            final = "direct"

    # локальные сети идём напрямую (в TUN это обязательно)
    rules.append({
        "action": "route",
        "ip_cidr": list(_LOCAL_CIDRS),
        "outbound": "direct",
    })

    inbounds: list[dict[str, Any]] = []
    if mode == "tun":
        # адрес подбирается по свободным интерфейсам (win/tunaddr): зашитый
        # 172.19.0.1/30 занят чужим VPN -> 'The object already exists' и TUN
        # не поднимается. Первый кандидат исторический, паритет с 1.0.6.
        # Отклонения от 1.0.6 (см. README, диагностика 30.09.2026):
        #
        # 1. strict_route=false. strict_route включает WFP-фильтры, которые
        #    БЛОКИРУЮТ порт 53 вне туннеля (документация sing-box). DNS-серверы
        #    Windows (роутер 192.168.0.1, Happ 172.19.0.2) ходят по конкретным
        #    маршрутам мимо туннеля -> весь DNS умирал, пока поднят туннель
        #    (TCP:53 -> WSAEACCES 10013, UDP:53 -> таймаут; проверено вживую:
        #    DNS ожил сразу после смерти sing-box). Без WFP такие запросы
        #    просто отвечают, как и раньше. В 1.0.6 TUN вообще не работал,
        #    так что паритет здесь не на что опираться.
        #
        # 2. route_address вместо авто-маршрута 0.0.0.0/0. Чужой VPN (Happ)
        #    держит свой default 0.0.0.0/0 с метрикой 0 и выигрывает наш
        #    общий по метрике: системный трафик шёл мимо нашего туннеля.
        #    Маршруты /1 длиннее любого /0 -> наш туннель забирает весь
        #    интернет-трафик (longest prefix), не трогая чужие маршруты;
        #    локальные подсети (/24 и конкретные) всё ещё конкретнее и идут
        #    напрямую. Когда sing-box умирает - его /1 исчезают вместе с
        #    адаптером, чужие default возвращаются (нет чёрных дыр).
        # TUN - строго IPv4 (фикс «5-секундного клина», 02.10.2026):
        # IPv6-адрес на адаптере заставляет auto_route повесить ::/0 (metric 0)
        # поверх физического - весь IPv6 уходит в туннель, а наружу ему нечем:
        # на машине без глобального IPv6 direct-dial умирает на своём таймауте
        # (в singbox.log: "dial tcp [2a00:...]: i/o timeout" ровно 5.0s). TUN-стек
        # принимает TCP мгновенно, поэтому happy-eyeballs приложения отказа не
        # видит и НЕ откатывается на IPv4: соединение виснет и рвётся на ~5 c.
        # Это било по всем, кто идёт мимо ноды - по режиму include (final=direct),
        # где каждый не выбранный процесс получал обрыв на любом домене с AAAA.
        # Без v6-адреса ::/0 остаётся на физическом адаптере: kill switch его
        # блокирует (fail-closed), приложение откатывается на IPv4 и работает.
        # Проверено живьём 30.09.2026 на этой машине (диагностика hairpin).
        # IPv6 LAN (fe80/fc00) идёт своим ходом, как и раньше.
        inbounds.append({
            "type": "tun",
            "tag": "tun-in",
            "interface_name": "vpn-launcher-tun",
            "address": [a for a in choose_tun_addresses() if ":" not in a],
            "mtu": 1500,
            "auto_route": True,
            "strict_route": False,
            "route_address": ["0.0.0.0/1", "128.0.0.0/1"],
            "stack": "mixed",
        })
    else:
        inbounds.append({"type": "socks", "tag": "socks-in", "listen": "127.0.0.1", "listen_port": SOCKS_PORT})
        inbounds.append({"type": "http", "tag": "http-in", "listen": "127.0.0.1", "listen_port": SOCKS_PORT + 1})

    root = Path(install_root) if install_root is not None else _default_install_root()
    return {
        "log": {"level": "info", "timestamp": True},
        "dns": {
            "servers": [
                {"tag": "dns-local", "type": "local"},
                {"tag": "dns-out", "type": "udp", "server": "1.1.1.1", "server_port": 53},
            ],
            "final": "dns-out",
        },
        "inbounds": inbounds,
        "outbounds": out,
        "route": {
            "rules": rules,
            "auto_detect_interface": True,
            "default_domain_resolver": {"server": "dns-local"},
            "final": final,
        },
        "experimental": {
            "cache_file": {"enabled": True, "path": str(root / "cache.db")},
        },
    }


def write_config(cfg: dict[str, Any], path: Path | str | None = None) -> Path:
    """[IO.File]::WriteAllText UTF-8 без BOM; JSON с 4 пробелами (как ConvertTo-Json)."""
    p = Path(path) if path is not None else CONFIG_FILE
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=4) + "\n", encoding="utf-8", newline="\n")
    return p


def purge_config_file(path: Path | str | None = None, *, retries: int = 20, delay: float = 0.05) -> bool:
    """Удалить config.json: креды нод не живут на диске дольше нужного.

    Безопасность (01.10.2026): файл пишется перед запуском движка и сразу
    удаляется (движок читает его на старте и закрывает); на автоперезапуске
    файл пересоздаётся из памяти. Пока Windows держит файл (движок читает),
    unlink отдаёт PermissionError - повторяем. Идемпотентно: файла нет ->
    True. False - не удалось удалить (оставляем, пишем в лог).
    """
    p = Path(path) if path is not None else CONFIG_FILE
    for _ in range(retries):
        try:
            if not p.exists():
                return True
            p.unlink()
            return True
        except PermissionError:
            time.sleep(delay)
        except OSError:
            break
    write_log("config.json: не удалось удалить (файл занят)")
    return False


def new_sing_box_config(
    nodes: Sequence[dict],
    selected: Sequence[str] = (),
    mode: str = "tun",
    app_list: Sequence[str] = (),
    test_url: str = DEFAULT_TEST_URL,
    only_selected: bool = False,
    app_mode: str = APP_MODE_EXCLUDE,
    *,
    install_root: Path | str | None = None,
    path: Path | str | None = None,
) -> Path:
    """New-SingBoxConfig дословно: сборка + запись файла + лог -> путь к config.json."""
    cfg = build_sing_box_config(
        nodes, selected, mode, app_list, test_url, only_selected, app_mode,
        install_root=install_root,
    )
    p = write_config(cfg, path)
    # PS логирует этот список при сборке правил (core.ps1:530); в include
    # режиме это уже не «исключения», поэтому и префикс другой - иначе в
    # журнале видно ровно то, что делает конфиг
    if mode == "tun":
        routed_apps = _routed_apps(app_mode, app_list)
        if routed_apps:
            head = (
                "  vpn-include apps: "
                if app_mode == APP_MODE_INCLUDE
                else "  direct-exclude apps: "
            )
            write_log(head + ", ".join(routed_apps))
        # какой адрес достался TUN-адаптеру - иначе конфликт с чужим VPN
        # (win/tunaddr) виден только в singbox.log.err, который обрезается
        write_log("tun address: " + ", ".join(cfg["inbounds"][0]["address"]))
    summary = (
        f"config written: {len(cfg['outbounds'])} outbounds, "
        f"mode={mode}, final={cfg['route']['final']}"
    )
    if mode == "tun" and app_mode == APP_MODE_INCLUDE:
        # хвост только для нового режима: строка дефолтного режима остаётся
        # байт-в-байт паритетной с PS 1.0.6 (сверяют тесты)
        summary += ", apps=include"
    write_log(summary)
    return p


def test_sing_box_config(
    path: Path | str, *, sing_box: Path | str | None = None, timeout: float = 30
) -> tuple[bool, str]:
    """Test-SingBoxConfig: `sing-box check -c <path>` -> (ok, stderr-текст).

    FileNotFoundError, если движок не найден (как Start-Process в PS);
    OSError - контроль целостности не прошёл (движок подменён/битый).
    """
    exe = Path(sing_box) if sing_box is not None else Path(SING_BOX)
    if sing_box is None:
        # Безопасность (01.10.2026): проверка ПЕРЕД exec - `check` тоже
        # запускает бинарник, подменённый движок не должен выполниться.
        # Сверяем только «свой» движок (путь по умолчанию); явный
        # sing_box= - тестовые прогоны с другим бинарём.
        from vpn_launcher.win.proc import verify_engine  # локальный: без цикла импортов

        verify_engine(exe)
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW, как -NoNewWindow
    proc = subprocess.run(
        [str(exe), "check", "-c", str(path)],
        capture_output=True,
        timeout=timeout,
        **kwargs,
    )
    err = proc.stderr.decode("utf-8", errors="replace")
    err = _ANSI_RE.sub("", err).strip()
    if not err:
        err = "без вывода"
    return proc.returncode == 0, err
