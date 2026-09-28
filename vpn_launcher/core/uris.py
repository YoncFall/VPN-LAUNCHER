# -*- coding: utf-8 -*-
"""URI-хелперы. Дословный порт src/core.ps1, строки 53-103.

PowerShell -> Python:
    Split-Uri               -> split_uri
    ConvertFrom-QueryString -> parse_query
    Split-HostPort          -> split_host_port
    Get-QueryVal            -> get_query_val
    Get-BoolVal             -> get_bool_val
"""
from __future__ import annotations

import re
from urllib.parse import unquote

_BRACKET_HOSTPORT = re.compile(r"^\[(?P<h>.+)\]:(?P<p>\d+)$")
_HOSTPORT = re.compile(r"^(?P<h>.+):(?P<p>\d+)$")
_TRUTHY = re.compile(r"^(1|true|yes|on)$", re.IGNORECASE)


def split_uri(uri: str) -> dict[str, str]:
    """Split-Uri -> {Scheme, Body, Query, Fragment} (все ключи всегда есть)."""
    res = {"Scheme": "", "Body": "", "Query": "", "Fragment": ""}
    rest = uri.strip()
    i = rest.find("://")
    if i < 0:
        return res
    res["Scheme"] = rest[:i].lower()
    rest = rest[i + 3:]

    h = rest.find("#")
    if h >= 0:
        res["Fragment"] = unquote(rest[h + 1:])
        rest = rest[:h]

    q = rest.find("?")
    if q >= 0:
        res["Query"] = rest[q + 1:]
        rest = rest[:q]

    res["Body"] = rest
    return res


def parse_query(q: str) -> dict[str, str]:
    """ConvertFrom-QueryString -> dict; повторяющиеся ключи: последний выигрывает."""
    out: dict[str, str] = {}
    if not q:
        return out
    for pair in q.split("&"):
        if not pair:
            continue
        p = pair.split("=", 1)
        k = unquote(p[0])
        v = unquote(p[1]) if len(p) > 1 else ""
        if k:
            out[k] = v
    return out


def split_host_port(s: str) -> tuple[str, int]:
    """Split-HostPort: 'host:8443' | '[::1]:443' | 'host' -> (host, port=443)."""
    m = _BRACKET_HOSTPORT.match(s)
    if m:
        return m.group("h"), int(m.group("p"))
    m = _HOSTPORT.match(s)
    if m:
        return m.group("h"), int(m.group("p"))
    return s, 443


def get_query_val(q: dict[str, str], names: list[str], default: str = "") -> str:
    """Get-QueryVal: первое имя с непустым значением, иначе default."""
    for n in names:
        if n in q and q[n] != "":
            return q[n]
    return default


def get_bool_val(q: dict[str, str], names: list[str], default: bool = False) -> bool:
    """Get-BoolVal: '1|true|yes|on' (регистр не важен), пусто -> default."""
    v = get_query_val(q, names, "")
    if v == "":
        return default
    return bool(_TRUTHY.match(v))
