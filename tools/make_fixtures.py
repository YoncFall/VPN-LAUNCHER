# -*- coding: utf-8 -*-
"""Генератор фикстур подписки для golden-тестов этапа 1.

Создаёт tests/fixtures/subscription.txt («сырая» подписка со всеми
протоколами и краевыми случаями core.ps1) и subscription-b64.txt
(тот же текст, обёрнутый в base64 - второй вход Parse-NodeList).

Оба файла читаются и PowerShell-скриптом tools/make_golden.ps1, и
pytest-тестами, поэтому паритет 1.0.6 проверяется на одних и тех же
данных. Перегенерация: venv\\Scripts\\python.exe tools\\make_fixtures.py
"""
from __future__ import annotations

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def b64(s: str) -> str:
    """ConvertTo-B64Utf8: стандартный base64 от UTF-8."""
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def vmess(json_body: str) -> str:
    return "vmess://" + b64(json_body)


# vmess: type:"none" (тип заголовка) перебивает net в Get-QueryVal (core.ps1:139) ->
# в 1.0.6 transport НЕ строится; здесь сохранено для паритета.
VM1 = (
    '{"v":"2","ps":"VMess-WS","add":"vmess-ws.example.com","port":"443",'
    '"id":"44444444-4444-4444-4444-444444444444","aid":"0","scy":"auto",'
    '"net":"ws","type":"none","host":"cdn.example.com","path":"/vmess-ws","tls":""}'
)
# vmess+tls: $q в PS пересобирается только из security/sni/fp/alpn ->
# transport теряется (баг 1.0.6, сохранён); aid=2 проверяет alter_id.
VM2 = (
    '{"v":"2","ps":"VMess-TLS","add":"vmess-tls.example.com","port":8443,'
    '"id":"55555555-5555-5555-5555-555555555555","aid":"2",'
    '"net":"ws","host":"secure.example.com","path":"/ws2",'
    '"tls":"tls","sni":"vmess-tls.example.com","fp":"chrome","alpn":"h2"}'
)
# vmess без поля type и без tls: единственная ветка, где ws-transport реально строится.
VM3 = (
    '{"ps":"VMess-Bare","add":"vmess-bare.example.com","port":"2053",'
    '"id":"66666666-6666-6666-6666-666666666666","aid":"1",'
    '"net":"ws","host":"bare-cdn.example.com","path":"/bare"}'
)

# Разбор по строкам: только строки с '://' участвуют в нумерации (Parse-NodeList:436).
# 16 нод + 4 строки дают None (сломанный vless, http, socks, неизвестная схема).
# ВАЖНО (поведение 1.0.6): если ПЕРВЫЙ непробельный символ текста не схема и не
# b64 - Parse-NodeList склеивает весь текст в одну строку и ломает разбор.
# Поэтому подписка начинается сразу с URI, комментарии - только в середине.
LINES = [
    # 1: vless + tls + ws (+utls, alpn из %2C/%2F)
    "vless://11111111-1111-1111-1111-111111111111@vless-ws.example.com:443"
    "?security=tls&sni=vless-ws.example.com&fp=chrome&alpn=h2%2Chttp%2F1.1"
    "&type=ws&path=%2Fws&host=cdn.example.com#VLESS-WS-TLS",
    # 2: reality (pbk/sid/flow); pbk - валидный X25519 pubkey (RFC 7748), иначе
    # sing-box check падает с "invalid public_key" (проверено)
    "vless://22222222-2222-2222-2222-222222222222@reality.example.com:8443"
    "?security=reality&sni=www.microsoft.com&fp=chrome"
    "&pbk=hSDwCYkwp1R0i33ctD73Wg2_Og0mOBr066SpjqqbTmo"
    "&sid=a1b2c3d4&flow=xtls-rprx-vision#VLESS-Reality",
    # 3: без параметров, фрагмент с кириллицей в percent-виде -> display «Сервер VLESS»
    "vless://33333333-3333-3333-3333-333333333333@plain-tcp.example.com:8080"
    "#%D0%A1%D0%B5%D1%80%D0%B2%D0%B5%D1%80%20VLESS",
    # 4: httpupgrade-транспорт
    "vless://77777777-7777-7777-7777-777777777777@up.example.com:443"
    "?type=httpupgrade&path=%2Fup&host=up.example.com#VLESS-HttpUpgrade",
    # 5: vmess, type=none перебивает net (см. VM1)
    vmess(VM1),
    # 6: vmess+tls (см. VM2), port как число
    vmess(VM2),
    # 7: vmess c ws-transport (см. VM3)
    vmess(VM3),
    # 8: ss, userinfo в base64
    "ss://" + b64("aes-256-gcm:ss-password") + "@ss-userinfo.example.com:8388#SS-Userinfo",
    # 9: ss, ВСЁ тело в base64 + plugin obfs-local
    "ss://" + b64("chacha20-ietf-poly1305:ss2pass@ss-body.example.com:8389")
    + "?plugin=obfs-local&plugin-opts=example.com#SS-Body-Obfs",
    # 10: ss, userinfo вообще без base64 (дефолтный фолбэк ConvertFrom-B64Utf8)
    "ss://aes-128-gcm:ss3pass@ss-raw.example.com:8390#SS-Raw",
    # 11: ss + v2ray-plugin
    "ss://" + b64("aes-256-gcm:ss4pass") + "@ss-v2.example.com:8391"
    "?plugin=v2ray-plugin;mode=websocket#SS-V2Ray",
    # 12: trojan + grpc, явный tls
    "trojan://trojan-pass@trojan-grpc.example.com:443"
    "?security=tls&sni=trojan-grpc.example.com&type=grpc&serviceName=trojan-grpc"
    "&alpn=h2#Trojan-Grpc",
    # 13: trojan вообще без query -> tls всё равно включён (tls_by_default)
    "trojan://plain-pass@trojan-plain.example.com:443#Trojan-Plain",
    # 14: hysteria2 + insecure + salamander
    "hysteria2://hy2-pass@hy2.example.com:8443"
    "?sni=hy2.example.com&insecure=1&alpn=h3&obfs=salamander&obfs-password=obfs-secret#HY2-Obfs",
    # 15: схема-алиас hy2, без пароля (at < 0)
    "hy2://hy2-plain.example.com:443#HY2-Plain",
    # 16: tuic, congestion_control не bbr
    "tuic://6ba7b810-9dad-11d1-80b4-00c04fd430c8:tuic-pass@tuic.example.com:443"
    "?congestion_control=cubic&sni=tuic.example.com&insecure=true&alpn=h3#TUIC-Cubic",
    # ниже - строки с '://' которые парсер обязан ВЕРНУТЬ None;
    # валидные URI уже закончились, поэтому комментарии ниже безопасны:
    "# сломанные и отброшенные схемы (индексы строк всё равно считаются):",
    "vless://missing-at-sign#Broken-VLESS",          # нет '@'
    "wireguard://wg.example.com#Ignored-Unknown",     # неизвестная схема
    "http://example.com:8080#Ignored-HTTP",           # http -> $null
    "socks://user:pass@socks.example.com:1080#Ignored-Socks",  # socks -> $null
    "",
    "# подписка-пример: комментарии и пустые строки отбрасываются",
]

FIXTURE_B64_HEADER_NOTE = (
    "b64-файл должен содержать ТОЛЬКО base64 (без комментариев): иначе "
    "Parse-NodeList не распознает его и склеит в одну строку"
)


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    plain = "\n".join(LINES) + "\n"
    (FIXTURES / "subscription.txt").write_text(plain, encoding="utf-8", newline="\n")
    # base64 - чистая строка без комментариев (см. FIXTURE_B64_HEADER_NOTE)
    (FIXTURES / "subscription-b64.txt").write_text(b64(plain) + "\n", encoding="utf-8", newline="\n")
    nodes = sum(1 for l in LINES if "://" in l)
    print(f"fixtures written: {FIXTURES} ({nodes} '://' lines)")


if __name__ == "__main__":
    main()
