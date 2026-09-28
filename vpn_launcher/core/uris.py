# -*- coding: utf-8 -*-
"""URI-хелперы и парсеры протоколов. Дословный порт src/core.ps1, строки 35-388.

PowerShell -> Python:
    ConvertFrom-B64Utf8     -> b64_utf8_decode
    ConvertTo-B64Utf8       -> b64_utf8_encode
    Split-Uri               -> split_uri
    ConvertFrom-QueryString -> parse_query
    Split-HostPort          -> split_host_port
    Get-QueryVal            -> get_query_val
    Get-BoolVal             -> get_bool_val
    New-TlsBlock            -> new_tls_block
    New-TransportBlock      -> new_transport_block
    ConvertFrom-ProxyUri    -> parse_proxy_uri

Замечания порта (сознательно, поведение 1.0.6 сохранено дословно):
  - в ConvertFrom-ProxyUri локальная переменная $name в PS нигде не
    используется (display считается в Parse-NodeList) - здесь её нет;
  - vmess: при tls/reality $q в PS пересобирается ТОЛЬКО из security/sni/fp/alpn,
    поэтому transport у vmess+tls не появляется (баг 1.0.6, сохранён ради паритета);
  - сообщение log-строки "parse error ..." формируется тем же шаблоном,
    текст исключения может отличаться от .NET (это только журнал).
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any, Callable
from urllib.parse import unquote

from vpn_launcher.core.log import write_log

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


# ---------------- b64 (core.ps1:35-51) ----------------


def b64_utf8_decode(s: str) -> str:
    """ConvertFrom-B64Utf8: trim, url-safe -> standard, паддинг, UTF-8; '' при ошибке."""
    if not s:
        return ""
    t = re.sub(r"\s", "", s.strip())
    t = t.replace("-", "+").replace("_", "/")
    rem = len(t) % 4
    if rem == 2:
        t += "=="
    elif rem == 3:
        t += "="
    elif rem == 1:
        return ""
    try:
        raw = base64.b64decode(t, validate=True)
    except (binascii.Error, ValueError):
        return ""
    # как Encoding.UTF8.GetString в .NET: невалидные байты -> символы замены
    return raw.decode("utf-8", errors="replace")


def b64_utf8_encode(s: str) -> str:
    """ConvertTo-B64Utf8: UTF-8 -> standard base64."""
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


# ---------------- TLS/транспорт (core.ps1:105-182) ----------------


def new_tls_block(q: dict[str, str], default_sni: str, tls_by_default: bool) -> dict[str, Any] | None:
    """New-TlsBlock -> dict | None (как в PS: хеш-таблица или $null)."""
    sec = get_query_val(q, ["security"], "").lower()
    is_reality = sec == "reality"
    enabled = tls_by_default or sec == "tls" or is_reality
    if not enabled:
        return None

    sni = get_query_val(q, ["sni", "peer", "host"], default_sni)
    fp = get_query_val(q, ["fp"], "")
    insec = get_bool_val(q, ["allowInsecure", "insecure", "allow_insecure"], False)
    alpn = get_query_val(q, ["alpn"], "")

    tls: dict[str, Any] = {"enabled": True, "server_name": sni}
    if insec:
        tls["insecure"] = True
    if fp:
        tls["utls"] = {"enabled": True, "fingerprint": fp}
    if alpn:
        tls["alpn"] = alpn.split(",")

    if is_reality:
        pbk = get_query_val(q, ["pbk", "public-key", "publicKey"], "")
        sid = get_query_val(q, ["sid", "short-id", "shortId"], "")
        r: dict[str, Any] = {"enabled": True}
        if pbk:
            r["public_key"] = pbk
        if sid:
            r["short_id"] = sid
        tls["reality"] = r
        if not sni:
            tls["server_name"] = get_query_val(q, ["host"], "")
    return tls


def new_transport_block(q: dict[str, str], default_host: str) -> dict[str, Any] | None:
    """New-TransportBlock -> dict | None."""
    net = get_query_val(q, ["type", "net", "network", "obfs"], "tcp").lower()
    path = get_query_val(q, ["path"], "")
    hst = get_query_val(q, ["host"], default_host)
    svc = get_query_val(q, ["serviceName", "servicename"], "")
    h_type = get_query_val(q, ["headerType"], "")

    if net in ("ws", "websocket"):
        t: dict[str, Any] = {"type": "ws"}
        if path:
            t["path"] = path
        if hst:
            t["headers"] = {"Host": hst}
        return t
    if net == "grpc":
        t = {"type": "grpc"}
        if svc:
            t["service_name"] = svc
        return t
    if net == "h2":
        t = {"type": "http"}
        if hst:
            t["host"] = hst.split(",")
        if path:
            t["path"] = path
        return t
    if net == "http":
        if h_type == "http":
            t = {"type": "http"}
            if path:
                t["path"] = path.split(",")
            if hst:
                t["host"] = hst.split(",")
            return t
        return None
    if net == "httpupgrade":
        t = {"type": "httpupgrade", "host": hst}
        if path:
            t["path"] = path
        return t
    if net == "quic":
        return {"type": "quic"}
    return None


# ---------------- парсеры протоколов (core.ps1:186-388) ----------------


def parse_proxy_uri(
    uri: str, index: int, *, logger: Callable[[str], None] = write_log
) -> dict[str, Any] | None:
    """ConvertFrom-ProxyUri -> dict ноды (с ключами type/tag/server/...) | None."""
    u = split_uri(uri)
    tag = f"node-{index}"

    try:
        scheme = u["Scheme"]

        if scheme == "vless":
            body = u["Body"]
            at = body.rfind("@")
            if at < 0:
                return None
            uuid = body[:at]
            host, port = split_host_port(body[at + 1:])
            q = parse_query(u["Query"])

            ob: dict[str, Any] = {
                "type": "vless",
                "tag": tag,
                "server": host,
                "server_port": port,
                "uuid": uuid,
            }
            flow = get_query_val(q, ["flow"], "")
            if flow:
                ob["flow"] = flow
            tls = new_tls_block(q, host, False)
            if tls:
                ob["tls"] = tls
            tr = new_transport_block(q, host)
            if tr:
                ob["transport"] = tr
            return ob

        if scheme == "vmess":
            # vmess://base64(json)
            raw = b64_utf8_decode(u["Body"])
            if not raw or not raw.lstrip().startswith("{"):
                return None
            j = json.loads(raw)
            if not isinstance(j, dict):
                return None

            srv = j.get("add") or j.get("address")
            if not srv:
                return None
            port = int(j["port"]) if j.get("port") else 443
            uuid = j.get("id") or j.get("ps")

            ob = {
                "type": "vmess",
                "tag": tag,
                "server": srv,
                "server_port": port,
                "uuid": uuid,
                "alter_id": 0,
            }
            aid = j.get("aid")
            if aid and int(aid) > 0:
                ob["alter_id"] = int(aid)

            q: dict[str, Any] = {}
            for k in ("net", "type", "host", "path", "tls", "sni", "alpn", "fp", "scy"):
                if k in j and j[k]:
                    q[k] = j[k]
            if j.get("tls") in ("tls", "reality"):
                # как в PS: $q ПОЛНОСТЬЮ пересобирается из этой строки,
                # net/type/host/path при этом теряются (см. докстринг модуля)
                qs = f"security={j['tls']}"
                if j.get("sni"):
                    qs += f"&sni={j['sni']}"
                if j.get("fp"):
                    qs += f"&fp={j['fp']}"
                if j.get("alpn"):
                    qs += f"&alpn={j['alpn']}"
                q = parse_query(qs)
                tls = new_tls_block(q, srv, False)
                if tls:
                    ob["tls"] = tls
            tr = new_transport_block(q, srv)
            if tr:
                ob["transport"] = tr
            return ob

        if scheme == "trojan":
            body = u["Body"]
            at = body.rfind("@")
            if at < 0:
                return None
            pw = body[:at]
            host, port = split_host_port(body[at + 1:])
            q = parse_query(u["Query"])

            ob = {
                "type": "trojan",
                "tag": tag,
                "server": host,
                "server_port": port,
                "password": pw,
            }
            tls = new_tls_block(q, host, True)
            if tls:
                ob["tls"] = tls
            tr = new_transport_block(q, host)
            if tr:
                ob["transport"] = tr
            return ob

        if scheme == "ss":
            body = u["Body"]
            if "@" in body:
                at = body.rfind("@")
                userinfo = body[:at]
                host, port = split_host_port(body[at + 1:])
                plain = b64_utf8_decode(userinfo)
                if ":" not in plain:
                    plain = userinfo
            else:
                dec = b64_utf8_decode(body)
                if "@" not in dec:
                    return None
                at = dec.rfind("@")
                plain = dec[:at]
                host, port = split_host_port(dec[at + 1:])

            ci = plain.find(":")
            if ci < 0:
                return None
            method = plain[:ci]
            password = plain[ci + 1:]

            q = parse_query(u["Query"])
            ob = {
                "type": "shadowsocks",
                "tag": tag,
                "server": host,
                "server_port": port,
                "method": method,
                "password": password,
            }
            if "plugin" in q:
                pl = q["plugin"]
                if "obfs-local" in pl:
                    ob["plugin"] = "obfs-local"
                    ob["plugin_opts"] = f"obfs=http;obfs-host={q.get('plugin-opts', '')}"
                elif "v2ray-plugin" in pl:
                    ob["plugin"] = "v2ray-plugin"
                    ob["plugin_opts"] = "mode=websocket"
            return ob

        if scheme in ("hysteria2", "hy2"):
            body = u["Body"]
            at = body.rfind("@")
            pw = body[:at] if at >= 0 else ""
            host, port = split_host_port(body[at + 1:] if at >= 0 else body)
            q = parse_query(u["Query"])

            ob = {
                "type": "hysteria2",
                "tag": tag,
                "server": host,
                "server_port": port,
                "password": pw,
            }
            sni = get_query_val(q, ["sni", "peer"], host)
            insec = get_bool_val(q, ["insecure", "allowInsecure"], False)
            ob["tls"] = {"enabled": True, "server_name": sni}
            if insec:
                ob["tls"]["insecure"] = True
            alpn = get_query_val(q, ["alpn"], "")
            if alpn:
                ob["tls"]["alpn"] = alpn.split(",")

            obfs = get_query_val(q, ["obfs"], "")
            obfs_pw = get_query_val(q, ["obfs-password", "obfs_password"], "")
            if not obfs_pw:
                obfs_pw = get_query_val(q, ["obfsParam"], "")
            if obfs and obfs_pw:
                ob["obfs"] = {"type": "salamander", "password": obfs_pw}
            return ob

        if scheme == "tuic":
            body = u["Body"]
            at = body.rfind("@")
            if at < 0:
                return None
            cred = body[:at]
            host, port = split_host_port(body[at + 1:])
            q = parse_query(u["Query"])
            ci = cred.find(":")
            uuid = cred[:ci] if ci >= 0 else cred
            pw = cred[ci + 1:] if ci >= 0 else ""

            ob = {
                "type": "tuic",
                "tag": tag,
                "server": host,
                "server_port": port,
                "uuid": uuid,
                "password": pw,
                "congestion_control": get_query_val(q, ["congestion_control"], "bbr"),
            }
            sni = get_query_val(q, ["sni", "peer"], host)
            insec = get_bool_val(q, ["insecure", "allowInsecure"], False)
            ob["tls"] = {"enabled": True, "server_name": sni}
            if insec:
                ob["tls"]["insecure"] = True
            alpn = get_query_val(q, ["alpn"], "")
            if alpn:
                ob["tls"]["alpn"] = alpn.split(",")
            return ob

        # http/socks и любые неизвестные схемы -> None (как default в PS-switch)
        return None
    except Exception as exc:  # как catch в ConvertFrom-ProxyUri
        logger(f"parse error [{u['Scheme']}] {uri[:60]}: {exc}")
        return None
