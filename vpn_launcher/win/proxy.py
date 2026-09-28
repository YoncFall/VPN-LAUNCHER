# -*- coding: utf-8 -*-
"""Системный прокси. Порт Set-ProxyOn/Set-ProxyOff (VPN.ps1:440-454).

HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings:
  ON : ProxyEnable=1, ProxyServer='socks=127.0.0.1:N;http=127.0.0.1:N+1',
       ProxyOverride='localhost;127.*;10.*;172.16.*;192.168.*;<local>'
  OFF: только если ProxyEnable==1 -> ProxyEnable=0, ProxyServer=''

Как и в PS, здесь НЕТBroadcast-обновления (InternetSetOption) —
Windows подхватывает значения так же, как и раньше.
"""
from __future__ import annotations

import winreg

from vpn_launcher.core.log import write_log
from vpn_launcher.paths import SOCKS_PORT

_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
PROXY_OVERRIDE = "localhost;127.*;10.*;172.16.*;192.168.*;<local>"


def set_proxy_on(socks_port: int = SOCKS_PORT) -> None:
    server = f"socks=127.0.0.1:{socks_port};http=127.0.0.1:{socks_port + 1}"
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
