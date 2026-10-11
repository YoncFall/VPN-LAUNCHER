# -*- coding: utf-8 -*-
"""Генератор полезных грузов (fake-пакетов) для winws — СВОИ, не чужие.

Запуск (dev-only, нужен `pip install cryptography`; конечным пользователям
этот скрипт не нужен — сгенерированные .bin запакованы в zapret/bin):

    python tools/zapret/gen_payloads.py

Файлы детерминированы: фиксированные байты вместо случайных, поэтому
повторный запуск даёт байт-в-байт тот же результат (хэши сверяемы).

Что генерируется (всё с содержимым «www.google.com» — фейк должен
отличаться от реального трафика, иначе десинхронизация не работает):

  tls-clienthello-google.bin — полная TLS-запись с ClientHello
      (SNI www.google.com, ALPN h2/http1.1, TLS1.3+1.2, key_share x25519);
  quic-initial-google.bin    — QUIC v1 Initial (RFC 9000): внутри CRYPTO-
      фрейм с тем же ClientHello. Initial шифруется ключами, выводимыми
      из DCID (RFC 9000 §5.1-5.2): HKDF-SHA256 + AES-128-GCM + header
      protection. DPI читает Initial (ключи публичны), наш скрипт строит
      его сам. Пакет паддится до 1200 байт (RFC 9244/9000 anti-amp);
  stun-binding.bin           — STUN Binding Request + SOFTWARE-атрибут;
  discord-voice.bin          — Discord Voice IP Discovery (type 0x0001,
      length 70, SSRC + 66 байт), падд до 1200.

Самопроверка: собранный QUIC-пакет расшифровывается обратно теми же
ключами, ClientHello находится внутри — иначе скрипт падает с ошибкой.
"""
from __future__ import annotations

import hashlib
import hmac
import struct
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand

BIN_DIR = Path(__file__).resolve().parents[2] / "zapret" / "bin"
SNI = b"www.google.com"

# --- детерминированные «случайные» поля -------------------------------------
FIXED_RANDOM = bytes(range(0x21, 0x41))          # 32 байта client random
FIXED_SID = b"\xab" * 32                          # session id (совместимость)
FIXED_X25519 = hashlib.sha256(b"vpn-launcher fake key_share").digest()
FIXED_DCID = hashlib.sha256(b"vpn-launcher quic dcid").digest()[:8]
FIXED_TXID = hashlib.sha256(b"vpn-launcher stun txid").digest()[:12]
DISCORD_SSRC = 0x01020304

QUIC_V1_SALT = bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a")
QUIC_PAD_TO = 1200


def u8(n: int) -> bytes:
    return struct.pack("!B", n)


def u16(n: int) -> bytes:
    return struct.pack("!H", n)


def u24(n: int) -> bytes:
    return struct.pack("!I", n)[1:]


def u32be(n: int) -> bytes:
    return struct.pack("!I", n)


# --- TLS ClientHello --------------------------------------------------------

def _ext(etype: int, data: bytes) -> bytes:
    return u16(etype) + u16(len(data)) + data


def build_client_hello(sni: bytes = SNI) -> bytes:
    """Handshake ClientHello (без TLS-записи) — наш, детерминированный."""
    sn_entry = u8(0) + u16(len(sni)) + sni
    server_name = _ext(0x0000, u16(len(sn_entry)) + sn_entry)
    groups = u16(0x001D) + u16(0x0017) + u16(0x0018)  # x25519, p256, p384
    supported_groups = _ext(0x000A, u16(len(groups)) + groups)
    ec_point_formats = _ext(0x000B, u8(1) + u8(0))
    sigalgs = b"".join(
        u16(x) for x in (0x0403, 0x0804, 0x0401, 0x0503, 0x0805, 0x0501)
    )
    signature_algorithms = _ext(0x000D, u16(len(sigalgs)) + sigalgs)
    alpn_proto = u8(2) + b"h2" + u8(8) + b"http/1.1"
    alpn = _ext(0x0010, u16(len(alpn_proto)) + alpn_proto)
    versions = u16(0x0304) + u16(0x0303)  # TLS1.3, TLS1.2
    supported_versions = _ext(0x002B, u8(len(versions)) + versions)
    psk_modes = _ext(0x002D, u8(1) + u8(1))  # psk_dhe_ke
    share = u16(0x001D) + u16(len(FIXED_X25519)) + FIXED_X25519
    key_share = _ext(0x0033, u16(len(share)) + share)

    ciphers = b"".join(
        u16(x)
        for x in (0x1301, 0x1302, 0x1303, 0xC02B, 0xC02F, 0xC02C, 0xC030,
                  0xCCA9, 0xCCA8)
    )
    extensions = (
        server_name + supported_groups + ec_point_formats + signature_algorithms
        + alpn + supported_versions + psk_modes + key_share
    )
    body = (
        u16(0x0303) + FIXED_RANDOM + u8(len(FIXED_SID)) + FIXED_SID
        + u16(len(ciphers)) + ciphers + u8(1) + u8(0)
        + u16(len(extensions)) + extensions
    )
    return u8(1) + u24(len(body)) + body  # handshake type=client_hello


def build_tls_record(handshake: bytes) -> bytes:
    return u8(0x16) + u16(0x0301) + u16(len(handshake)) + handshake


# --- QUIC v1 Initial (RFC 9000 §5, §13) ------------------------------------

def _varint(n: int) -> bytes:
    if n < 64:
        return u8(n)
    if n < 16384:
        return u16(n | 0x4000)
    if n < 1 << 30:
        return struct.pack("!I", n | 0x80000000)
    return struct.pack("!I", n | 0xC0000000)


def _hkdf_expand_label(secret: bytes, label: bytes, length: int) -> bytes:
    """HKDF-Expand-Label из TLS1.3 с префиксом 'tls13 ' (RFC 9000 §5.1)."""
    full = b"tls13 " + label
    hkdf_label = u16(length) + u8(len(full)) + full + u8(0)
    return HKDFExpand(algorithm=hashes.SHA256(), length=length,
                      info=hkdf_label).derive(secret)


def build_quic_initial(handshake: bytes) -> bytes:
    """Initial-пакет QUIC v1 с CRYPTO(ClientHello) внутри, падд до 1200."""
    # HKDF-Extract(salt, ikm) = HMAC-SHA256(salt, ikm)
    initial_secret = hmac.new(QUIC_V1_SALT, FIXED_DCID, hashlib.sha256).digest()
    csecret = _hkdf_expand_label(initial_secret, b"client in", 32)
    key = _hkdf_expand_label(csecret, b"quic key", 16)
    iv = _hkdf_expand_label(csecret, b"quic iv", 12)
    hp_key = _hkdf_expand_label(csecret, b"quic hp", 16)

    crypto_frame = u8(0x06) + _varint(0) + _varint(len(handshake)) + handshake
    # заголовок: first + version + dcid_len + dcid + token_len(0) + lenvarint(2)
    # + pn(1); длина 2-байтового varint устойчива при cipher_len ~1182
    header_len = 1 + 4 + 1 + len(FIXED_DCID) + 1 + 2 + 1
    cipher_len = QUIC_PAD_TO - header_len
    payload_len = cipher_len - 16  # вычет тега GCM
    pad = payload_len - len(crypto_frame)
    if pad < 0:
        raise RuntimeError("ClientHello не влезает в Initial")
    payload = crypto_frame + b"\x00" * pad

    first = 0xC1  # long header, Initial, PN length = 1
    pn = b"\x00"
    length_field = _varint(1 + cipher_len)
    assert len(length_field) == 2, "ожидался 2-байтовый varint длины"
    header = (u8(first) + u32be(1) + u8(len(FIXED_DCID)) + FIXED_DCID + u8(0)
              + length_field)
    aad = header + pn
    nonce = bytes(a ^ b for a, b in zip(iv, b"\x00" * 7 + pn))
    ct = AESGCM(key).encrypt(nonce, payload, aad)  # ciphertext + tag

    # header protection (RFC 9000 §5.4): sample из ciphertext
    sample = ct[4:20]
    mask = Cipher(algorithms.AES(hp_key), modes.ECB()).encryptor().update(sample)
    first_protected = first ^ (mask[0] & 0x0F)
    pn_protected = bytes(p ^ m for p, m in zip(pn, mask[1:2]))
    packet = bytes([first_protected]) + aad[1:-1] + pn_protected + ct

    # --- самопроверка: обратная расшифровка ---
    mask2 = Cipher(algorithms.AES(hp_key), modes.ECB()).encryptor().update(ct[4:20])
    assert packet[0] ^ (mask2[0] & 0x0F) == first, "header protection не сходится"
    assert len(packet) == QUIC_PAD_TO, "пакет должен быть ровно 1200 байт"
    pt = AESGCM(key).decrypt(nonce, ct, aad)
    assert pt == payload and handshake in pt, "GCM round-trip не сошёлся"
    return packet


# --- STUN / Discord ---------------------------------------------------------

def build_stun_binding() -> bytes:
    """STUN Binding Request + SOFTWARE-атрибут (всего 100 байт)."""
    software = b"VPN-LAUNCHER fake stun payload 0123456789abcdef".ljust(76, b".")
    attr = u16(0x8022) + u16(len(software)) + software
    header = (u16(0x0001) + u16(len(attr)) + u16(0x2112) + u16(0xA442)
              + FIXED_TXID)
    return header + attr


def build_discord_voice() -> bytes:
    """Discord Voice IP Discovery: type 0x0001, length 70, SSRC + 66 байт."""
    tail = b"0.0.0.0".ljust(64, b"\x00") + u16(0)  # ip string + port
    body = u16(0x0001) + u16(70) + u32be(DISCORD_SSRC) + tail
    assert len(body) == 74
    return body + b"\x00" * (QUIC_PAD_TO - len(body))


def main() -> None:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    handshake = build_client_hello()
    files = {
        "tls-clienthello-google.bin": build_tls_record(handshake),
        "quic-initial-google.bin": build_quic_initial(handshake),
        "stun-binding.bin": build_stun_binding(),
        "discord-voice.bin": build_discord_voice(),
    }
    for name, data in files.items():
        (BIN_DIR / name).write_bytes(data)
        print("%-28s %5d B  sha256=%s" % (
            name, len(data), hashlib.sha256(data).hexdigest()[:32]))


if __name__ == "__main__":
    main()
