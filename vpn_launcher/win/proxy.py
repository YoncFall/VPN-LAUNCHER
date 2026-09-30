# -*- coding: utf-8 -*-
"""Системный прокси. Порт Set-ProxyOn/Set-ProxyOff (VPN.ps1:440-454).

HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings:
  ON : ProxyEnable=1, ProxyServer='socks=127.0.0.1:N;http=127.0.0.1:N+1',
       ProxyOverride='localhost;127.*;10.*;172.16.*;192.168.*;<local>'
  OFF: только если ProxyEnable==1 -> ProxyEnable=0, ProxyServer=''
  STARTUP: снимаем ТОЛЬКО наш точный ProxyServer включённым - сирота после
       краша в прокси-режиме (иначе приложения без интернета); чужие прокси
       не трогаем. Паритет с 1.0.6 нарушен сознательно (PS такого не делал).

Как и в PS, здесь НЕТBroadcast-обновления (InternetSetOption) —
Windows подхватывает значения так же, как и раньше.
"""
from __future__ import annotations

import winreg

from vpn_launcher.core.log import write_log
from vpn_launcher.paths import SOCKS_PORT

_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
PROXY_OVERRIDE = "localhost;127.*;10.*;172.16.*;192.168.*;<local>"


def _server_value(socks_port: int = SOCKS_PORT) -> str:
    return f"socks=127.0.0.1:{socks_port};http=127.0.0.1:{socks_port + 1}"


def set_proxy_on(socks_port: int = SOCKS_PORT) -> None:
    server = _server_value(socks_port)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, server)
        winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, PROXY_OVERRIDE)
    write_log(f"system proxy ON 127.0.0.1:{socks_port}")


def set_proxy_off() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0, winreg.KEY_READ) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
    except OSError:
        enabled = None
    if enabled != 1:
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, "")
    write_log("system proxy OFF")


def startup_proxy_cleanup() -> bool:
    """Сирота от прошлого запуска: снять НАШ включённый системный прокси.

    Краш в прокси-режиме оставляет ProxyEnable=1 + ProxyServer, указывающий
    на мёртвый порт: приложения, читающие системный прокси, без интернета.
    Снимаем только точное совпадение нашего формата (чужие прокси не трогаем).
    Вызывается из main() ПОСЛЕ захвата мьютекса - живой экземпляр не пострадает.
    True - прокси был наш и снят.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0, winreg.KEY_READ) as key:
            enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
    except OSError:
        return False
    if enabled != 1 or server != _server_value():
        return False
    write_log("system proxy: сирота прошлого запуска - снимаю")
    set_proxy_off()
    return True
