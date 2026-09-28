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
  - сравнение тегов в only_selected регистрозависимое, как PS `-contains`.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from vpn_launcher.core.log import write_log
from vpn_launcher.paths import CONFIG_FILE, SOCKS_PORT, SING_BOX
from vpn_launcher.paths import install_root as _default_install_root

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


def build_sing_box_config(
    nodes: Sequence[dict],
    selected: Sequence[str] = (),
    mode: str = "tun",
    app_list: Sequence[str] = (),
    test_url: str = DEFAULT_TEST_URL,
    only_selected: bool = False,
    *,
    install_root: Path | str | None = None,
) -> dict[str, Any]:
    """New-SingBoxConfig без записи файла -> dict конфига (для golden-тестов).

    install_root - корень для cache.db (по умолчанию paths.install_root(),
    как $script:InstallRoot в PS); для тестов можно передать фиктивный путь.
    """
    if mode not in ("tun", "proxy"):
        raise ConfigError(f"Неизвестный режим: {mode!r} (ожидается 'tun' или 'proxy')")

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
    final = "proxy-group"

    # маршрутизация
    rules: list[dict[str, Any]] = [{"action": "sniff"}, {"protocol": "dns", "action": "hijack-dns"}]

    # per-app: перечисленные приложения идут НАПРЯМУЮ (важно для игр/античита)
    # action обязателен с sing-box 1.11, outbound внутри правила помечен deprecated
    direct_apps = _uniq(list(GAME_SAFE_PROCESSES) + list(app_list))
    if mode == "tun" and direct_apps:
        rules.append({
            "action": "route",
            "process_name": direct_apps,
            "outbound": "direct",
        })

    # локальные сети идём напрямую (в TUN это обязательно)
    rules.append({
        "action": "route",
        "ip_cidr": list(_LOCAL_CIDRS),
        "outbound": "direct",
    })

    inbounds: list[dict[str, Any]] = []
    if mode == "tun":
        inbounds.append({
            "type": "tun",
            "tag": "tun-in",
            "interface_name": "vpn-launcher-tun",
            "address": ["172.19.0.1/30", "fdfe:dcba:9876::1/126"],
            "mtu": 1500,
            "auto_route": True,
            "strict_route": True,
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


def new_sing_box_config(
    nodes: Sequence[dict],
    selected: Sequence[str] = (),
    mode: str = "tun",
    app_list: Sequence[str] = (),
    test_url: str = DEFAULT_TEST_URL,
    only_selected: bool = False,
    *,
    install_root: Path | str | None = None,
    path: Path | str | None = None,
) -> Path:
    """New-SingBoxConfig дословно: сборка + запись файла + лог -> путь к config.json."""
    cfg = build_sing_box_config(
        nodes, selected, mode, app_list, test_url, only_selected, install_root=install_root
    )
    p = write_config(cfg, path)
    # PS логирует этот список при сборке правил (core.ps1:530)
    if mode == "tun":
        direct_apps = _uniq(list(GAME_SAFE_PROCESSES) + list(app_list))
        if direct_apps:
            write_log("  direct-exclude apps: " + ", ".join(direct_apps))
    write_log(f"config written: {len(cfg['outbounds'])} outbounds, mode={mode}, final={cfg['route']['final']}")
    return p


def test_sing_box_config(
    path: Path | str, *, sing_box: Path | str | None = None, timeout: float = 30
) -> tuple[bool, str]:
    """Test-SingBoxConfig: `sing-box check -c <path>` -> (ok, stderr-текст).

    FileNotFoundError, если движок не найден (как Start-Process в PS).
    """
    exe = Path(sing_box) if sing_box is not None else Path(SING_BOX)
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
