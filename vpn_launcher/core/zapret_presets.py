# -*- coding: utf-8 -*-
"""Стратегии обхода DPI (winws) - НАШИ, собраны из задокументированных опций.

Источник опций: справка winws официального релиза zapret v72.13
(nfq/nfqws.c, секция TAMPER: --dpi-desync и производные, --dry-run и т.д.).
Сам winws - официальный бинарь bol-van (см. zapret/VERSION.txt: хэши
сверены с официальным sha256sum.txt релиза). Комбинации техник придуманы
для этого лаунчера (ни одна не скопирована из чужих .bat) и гоняются
автоподбором: HTTPS/TCP (fake-ClientHello google + дробление), HTTP,
QUIC (fake-Initial google), Discord-голос/STUN.

Каждая стратегия = одна командная строка winws: общий хвост
(--wf-*, --hostlist*) + четыре цепочки через --new:
    TLS 443  - варианты техники (здесь отличия между стратегиями);
    HTTP 80  - дробление метода;
    QUIC 443 - fake-Initial (google SNI);
    Discord/STUN UDP - fake-Discovery + fake-STUN.
Плейсхолдеры {BIN} и {LISTS} подставляет core.zapret.build_args.
"""
from __future__ import annotations

_FAKE_TLS = "+0@{BIN}tls-clienthello-google.bin"
_FAKE_QUIC = "+0@{BIN}quic-initial-google.bin"
_FAKE_DISCORD = "+0@{BIN}discord-voice.bin"
_FAKE_STUN = "+0@{BIN}stun-binding.bin"

_HEAD = (
    "--wf-tcp=80,443",
    "--wf-udp=443,19294-19344,50000-50100",
    "--hostlist={LISTS}list-general.txt",
    "--hostlist-exclude={LISTS}list-exclude.txt",
)

_HTTP = (
    "--filter-tcp=80",
    "--filter-l7=http",
    "--dpi-desync=multisplit",
    "--dpi-desync-autottl",
    "--dpi-desync-split-pos=method+1",
)

_QUIC = (
    "--filter-udp=443",
    "--filter-l7=quic",
    "--dpi-desync=fake",
    "--dpi-desync-autottl",
    f"--dpi-desync-fake-quic={_FAKE_QUIC}",
)

_DISCORD = (
    "--filter-udp=19294-19344,50000-50100",
    "--filter-l7=discord,stun",
    "--dpi-desync=fake",
    "--dpi-desync-autottl",
    f"--dpi-desync-fake-discord={_FAKE_DISCORD}",
    f"--dpi-desync-fake-stun={_FAKE_STUN}",
)


# --- варианты техники для TCP/443 (TLS) ------------------------------------

def _tls_fake_multisplit() -> tuple[str, ...]:
    """general: фейк google-ClientHello + дробление (основная ставка)."""
    return (
        "--filter-tcp=443",
        "--filter-l7=tls",
        "--dpi-desync=fake,multisplit",
        "--dpi-desync-autottl",
        "--dpi-desync-split-pos=1,midsld",
        f"--dpi-desync-fake-tls={_FAKE_TLS}",
        "--dpi-desync-fake-tcp-mod=seq",
        "--dpi-desync-fooling=badsum",
    )


def _tls_fake() -> tuple[str, ...]:
    """Только фейк, без дробления."""
    return (
        "--filter-tcp=443",
        "--filter-l7=tls",
        "--dpi-desync=fake",
        "--dpi-desync-autottl",
        f"--dpi-desync-fake-tls={_FAKE_TLS}",
        "--dpi-desync-fake-tcp-mod=seq",
        "--dpi-desync-fooling=badsum",
    )


def _tls_multisplit() -> tuple[str, ...]:
    """Только дробление, без фейков."""
    return (
        "--filter-tcp=443",
        "--filter-l7=tls",
        "--dpi-desync=multisplit",
        "--dpi-desync-split-pos=1,midsld",
    )


def _tls_disorder() -> tuple[str, ...]:
    """Дробление с переупорядочиванием сегментов."""
    return (
        "--filter-tcp=443",
        "--filter-l7=tls",
        "--dpi-desync=multidisorder",
        "--dpi-desync-split-pos=1,midsld",
    )


def _tls_disorder_fake() -> tuple[str, ...]:
    """Порядочный переупорядок + фейк."""
    return (
        "--filter-tcp=443",
        "--filter-l7=tls",
        "--dpi-desync=fake,multidisorder",
        "--dpi-desync-autottl",
        "--dpi-desync-split-pos=1,midsld",
        f"--dpi-desync-fake-tls={_FAKE_TLS}",
        "--dpi-desync-fake-tcp-mod=seq",
        "--dpi-desync-fooling=badsum",
    )


def _tls_hostfakesplit() -> tuple[str, ...]:
    """Фейковый сегмент внутри хостнейма."""
    return (
        "--filter-tcp=443",
        "--filter-l7=tls",
        "--dpi-desync=hostfakesplit",
        "--dpi-desync-split-pos=1",
        "--dpi-desync-fooling=badsum",
    )


def _tls_fakedsplit() -> tuple[str, ...]:
    """Фейковое приветствие перед дроблением."""
    return (
        "--filter-tcp=443",
        "--filter-l7=tls",
        "--dpi-desync=fakedsplit",
        "--dpi-desync-split-pos=midsld",
        f"--dpi-desync-fakedsplit-pattern={_FAKE_TLS}",
        "--dpi-desync-fooling=badsum",
    )


def _tls_headsplit() -> tuple[str, ...]:
    """Фейк + дробление по первому байту (без метки midsld)."""
    return (
        "--filter-tcp=443",
        "--filter-l7=tls",
        "--dpi-desync=fake,multisplit",
        "--dpi-desync-autottl",
        "--dpi-desync-split-pos=1",
        f"--dpi-desync-fake-tls={_FAKE_TLS}",
        "--dpi-desync-fake-tcp-mod=seq",
        "--dpi-desync-fooling=badsum",
    )


def _tls_repeats() -> tuple[str, ...]:
    """general, но каждый фейк отправляется дважды."""
    return _tls_fake_multisplit() + ("--dpi-desync-repeats=2",)


def _chain(name: str, tls: tuple[str, ...]) -> list[str]:
    return [f"--comment=vpl-{name}", *_HEAD,
            "--new", *tls,
            "--new", *_HTTP,
            "--new", *_QUIC,
            "--new", *_DISCORD]


PRESETS: list[dict] = [
    {"name": "general",       "args": _chain("general", _tls_fake_multisplit())},
    {"name": "fake",          "args": _chain("fake", _tls_fake())},
    {"name": "multisplit",    "args": _chain("multisplit", _tls_multisplit())},
    {"name": "disorder",      "args": _chain("disorder", _tls_disorder())},
    {"name": "disorder-fake", "args": _chain("disorder-fake", _tls_disorder_fake())},
    {"name": "hostfakesplit", "args": _chain("hostfakesplit", _tls_hostfakesplit())},
    {"name": "fakedsplit",    "args": _chain("fakedsplit", _tls_fakedsplit())},
    {"name": "headsplit",     "args": _chain("headsplit", _tls_headsplit())},
    {"name": "repeats",       "args": _chain("repeats", _tls_repeats())},
]
