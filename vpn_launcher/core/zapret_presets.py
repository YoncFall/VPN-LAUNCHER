# -*- coding: utf-8 -*-
"""Стратегии обхода DPI (winws) - НАШИ, собраны из задокументированных опций.

Источник опций: справка winws официального релиза zapret v72.13
(docs/readme.en.md: секция Multiple strategies, TAMPER) + фактический
успех отдельных техник на этой сети. Сам winws - официальный бинарь
bol-van (см. zapret/VERSION.txt: хэши сверены с официальным
sha256sum.txt релиза).

v3 (12.10.2026) - КОМБО = РЕПЛИКА ПРОВЕРЕННОЙ КОНФИГУРАЦИИ:
  Целую ночь (12.10, диагностика rate) ни одна «классическая» техника
  не снижала ~50% монетку на дискорде (fake, disorder, seqovl, синт-фейки
  - все ≈ baseline). Рабочая конфигурация из сообщества (zapret-discord,
  general ALT9) дала 8/8 на discord.com, gateway.discord.gg и youtube,
  и браузер открыл оба сайта. Ключ - hostfakesplit с fooling=ts,md5sig
  и подменой хоста на ozon.ru (дискорд-группа) / www.google.com (гугл).
  Комбо теперь повторяет её профиль в профиль ( QUIC, голос/STUN,
  медиа-альт-порты, google-группа, основной список, ipset-заглушки).

v2 (12.10.2026) - ПОСТРОЕНИЕ ПРОФИЛЕЙ:
  Профили разделяются --new, наследования НЕТ: у каждого профиля свой
  фильтр + свои списки + свой метод (документация: "Each profile has a
  filter... profiles are matched from the first to the last").
  В v1 списки жили в отдельном "голом" профиле №1 без метода: он
  перехватывал целевые хосты (discord/youtube) раньше профилей с методами
  - обход не срабатывал ВООБЩЕ, хотя winws работал. Теперь каждый профиль
  самодостаточен. Проверяется тестом test_every_profile_self_contained.

Техники TLS-профиля (варьируются между стратегиями):
  hostfakesplit - дробление с фейковым SNI (в комбо - ПРОВЕРЕННЫЙ победитель);
  seqovl       - наложение последовательностей (split + overlap + паттерн);
  fake         - фейковый ClientHello (+ повтор/дробление);
  disorder     - переупорядочивание сегментов;
  ts/md5sig    - fooling-режимы (подделка timestamp/md5 у реальных пакетов).
Каждая стратегия = одна командная строка winws, профили через --new:
    фильтр + списки + метод в каждом профиле (см. combo и _chain).
Плейсхолдеры {BIN} и {LISTS} подставляет core.zapret.build_args.
"""
from __future__ import annotations

_FAKE_TLS = "+0@{BIN}tls-clienthello-google.bin"
_FAKE_QUIC = "+0@{BIN}quic-initial-google.bin"
_FAKE_DISCORD = "+0@{BIN}discord-voice.bin"
_FAKE_STUN = "+0@{BIN}stun-binding.bin"
# паттерн seqovl-наложения: любой валидный ClientHello (наш google)
_SEQOVL_PATTERN = "+0@{BIN}tls-clienthello-google.bin"

_WF = (
    "--wf-tcp=80,443,2053,2083,2087,2096,8443",
    "--wf-udp=443,19294-19344,50000-50100",
)

# списки профиля (обязательны в каждом профиле с хост-фильтром);
# юзерские файлы редактируются через приложение
_EXCLUDE = (
    "--hostlist-exclude={LISTS}list-exclude.txt",
    "--hostlist-exclude={LISTS}list-exclude-user.txt",
)
_HOSTS = (
    "--hostlist={LISTS}list-general.txt",
    "--hostlist={LISTS}list-general-user.txt",
    *_EXCLUDE,
)

# --- общие профили (не меняются между стратегиями) --------------------------

_HTTP_TECH = (
    "--dpi-desync=multisplit",
    "--dpi-desync-split-seqovl=568",
    "--dpi-desync-split-pos=1",
    f"--dpi-desync-split-seqovl-pattern={_SEQOVL_PATTERN}",
)

_QUIC_TECH = (
    "--dpi-desync=fake",
    "--dpi-desync-autottl",
    "--dpi-desync-repeats=6",
    f"--dpi-desync-fake-quic={_FAKE_QUIC}",
)

_DISCORD_TECH = (
    "--dpi-desync=fake",
    "--dpi-desync-autottl",
    "--dpi-desync-repeats=6",
    f"--dpi-desync-fake-discord={_FAKE_DISCORD}",
    f"--dpi-desync-fake-stun={_FAKE_STUN}",
)

# альт-порты discord.media (звонки/стримы идут не на 443)
_MEDIA_TECH = (
    "--dpi-desync=fake,hostfakesplit",
    "--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com",
    "--dpi-desync-hostfakesplit-mod=host=www.google.com,altorder=1",
    "--dpi-desync-fooling=ts",
)

# --- варианты техники для TCP/443 (TLS) ------------------------------------

def _tls_seqovl() -> tuple[str, ...]:
    """general: наложение последовательностей - фейковые байты перед
    первым сегментом, DPI собирает мусор, сервер получает оригинал."""
    return (
        "--dpi-desync=multisplit",
        "--dpi-desync-split-seqovl=568",
        "--dpi-desync-split-pos=1",
        f"--dpi-desync-split-seqovl-pattern={_SEQOVL_PATTERN}",
    )


def _tls_fake_multisplit() -> tuple[str, ...]:
    """Фейк google-ClientHello + дробление."""
    return (
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
        "--dpi-desync=fake",
        "--dpi-desync-autottl",
        f"--dpi-desync-fake-tls={_FAKE_TLS}",
        "--dpi-desync-fake-tcp-mod=seq",
        "--dpi-desync-fooling=badsum",
    )


def _tls_multisplit() -> tuple[str, ...]:
    """Только дробление, без фейков."""
    return (
        "--dpi-desync=multisplit",
        "--dpi-desync-split-pos=1,midsld",
    )


def _tls_disorder() -> tuple[str, ...]:
    """Дробление с переупорядочиванием сегментов."""
    return (
        "--dpi-desync=multidisorder",
        "--dpi-desync-split-pos=1,midsld",
    )


def _tls_disorder_fake() -> tuple[str, ...]:
    """multidisorder + повторяющиеся фейки со сломанным seq (badseq):
    DPI принимает фейки за реальные пакеты и «запутывается», сервер их
    игнорирует по неверному номеру последовательности."""
    return (
        "--dpi-desync=fake,multidisorder",
        "--dpi-desync-split-pos=1,midsld",
        "--dpi-desync-repeats=11",
        "--dpi-desync-fooling=badseq",
        "--dpi-desync-fake-tls=!",
        "--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com",
    )


def _tls_hostfakesplit() -> tuple[str, ...]:
    """hostfakesplit с подменённым SNI (ya.ru) и порядком altorder:
    DPI видит безобидный хост, реальный уходит следом целым."""
    return (
        "--dpi-desync=fake,hostfakesplit",
        "--dpi-desync-fake-tls-mod=rnd,dupsid,sni=ya.ru",
        "--dpi-desync-hostfakesplit-mod=host=ya.ru,altorder=1",
        "--dpi-desync-fooling=ts",
    )


def _tls_fakedsplit() -> tuple[str, ...]:
    """Фейковое приветствие перед дроблением."""
    return (
        "--dpi-desync=fakedsplit",
        "--dpi-desync-split-pos=midsld",
        f"--dpi-desync-fakedsplit-pattern={_FAKE_TLS}",
        "--dpi-desync-fooling=badsum",
    )


def _tls_headsplit() -> tuple[str, ...]:
    """Фейк + дробление по первому байту (без метки midsld)."""
    return (
        "--dpi-desync=fake,multisplit",
        "--dpi-desync-autottl",
        "--dpi-desync-split-pos=1",
        f"--dpi-desync-fake-tls={_FAKE_TLS}",
        "--dpi-desync-fake-tcp-mod=seq",
        "--dpi-desync-fooling=badsum",
    )


def _tls_repeats() -> tuple[str, ...]:
    """Фейк + дробление, каждый фейк слать многократно."""
    return _tls_fake_multisplit() + ("--dpi-desync-repeats=11",)


def _tail() -> list[str]:
    """Общие профили (HTTP/QUIC/голос/media) - одинаковы для всех стратегий."""
    return [
        # 2. HTTP 80
        "--new",
        "--filter-tcp=80",
        "--filter-l7=http",
        *_HOSTS,
        *_HTTP_TECH,
        # 3. QUIC 443
        "--new",
        "--filter-udp=443",
        "--filter-l7=quic",
        *_HOSTS,
        *_QUIC_TECH,
        # 4. Discord-голос / STUN
        "--new",
        "--filter-udp=19294-19344,50000-50100",
        "--filter-l7=discord,stun",
        *_DISCORD_TECH,
        # 5. discord.media на альт-портах
        "--new",
        "--filter-tcp=2053,2083,2087,2096,8443",
        "--hostlist-domains=discord.media",
        *_EXCLUDE,
        *_MEDIA_TECH,
    ]


def _chain(name: str, tls: tuple[str, ...]) -> list[str]:
    """Пять самодостаточных профилей: фильтр + списки + метод в каждом."""
    return [
        f"--comment=vpl-{name}",
        *_WF,
        # 1. HTTPS/TLS 443
        "--filter-tcp=443",
        "--filter-l7=tls",
        *_HOSTS,
        *tls,
        *_tail(),
    ]


def _hfs(host: str, fooling: str, repeats: int) -> tuple[str, ...]:
    """hostfakesplit - дробление ClientHello с фейковым SNI из списка.

    Победитель 12.10: подменённый хост (ozon.ru для дискорда, www.google.com
    для гугла/медиа) + fooling=ts,md5sig убрали ~50% «монетку» убийства
    хендшейков, над которой бессильны fake/disorder/seqovl/синт-фейки."""
    return (
        "--dpi-desync=hostfakesplit",
        f"--dpi-desync-repeats={repeats}",
        f"--dpi-desync-fooling={fooling}",
        f"--dpi-desync-hostfakesplit-mod=host={host}",
    )


_QUIC_TECH_COMBO = (
    "--dpi-desync=fake",
    "--dpi-desync-repeats=6",
    f"--dpi-desync-fake-quic={_FAKE_QUIC}",
)

# голос/стун: фейк Discord Voice Discovery (для стуна - тот же файл,
# как в проверенной конфигурации-источнике)
_VOICE_TECH_COMBO = (
    "--dpi-desync=fake",
    "--dpi-desync-repeats=6",
    f"--dpi-desync-fake-discord={_FAKE_DISCORD}",
    f"--dpi-desync-fake-stun={_FAKE_DISCORD}",
)

# профили по ipset (пусто по умолчанию - для провайдеров, блокирующих по IP;
# юзер может заполнить ipset-all.txt своими адресами)
_EXCL_IPSET = (
    "--hostlist-exclude={LISTS}list-exclude.txt",
    "--hostlist-exclude={LISTS}list-exclude-user.txt",
    "--ipset-exclude={LISTS}ipset-exclude.txt",
    "--ipset-exclude={LISTS}ipset-exclude-user.txt",
)


def _combo_chain() -> list[str]:
    """Комбо = реплика проверенной рабочей конфигурации (v3, 12.10.2026).

    Источник: zapret-discord «general (ALT9)» - батник, подтверждённый
    пользователем как «работает отлично» и перепроверенный нами вживую:
    под ним discord.com 8/8, gateway.discord.gg 8/8, youtube 8/8, браузер
    открывает оба сайта (все прежние техники давали лишь ~50% на дискорде).
    Структура профиль-в-профиль: QUIC, голос/STUN, медиа-альт-порты,
    google-группа (list-google, ip-id=zero), основной список 80+443,
    ipset-заглушки (UDP/TCP) для провайдеров с блокировкой по IP.
    """
    return [
        "--comment=vpl-combo",
        *_WF,
        # 1. QUIC 443 (HTTP/3: youtube и все h3-хосты списка)
        "--filter-udp=443",
        "--filter-l7=quic",
        *_HOSTS,
        *_QUIC_TECH_COMBO,
        # 2. Discord-голос / STUN (звонки)
        "--new",
        "--filter-udp=19294-19344,50000-50100",
        "--filter-l7=discord,stun",
        *_VOICE_TECH_COMBO,
        # 3. discord.media на альт-портах (стримы/звонки не на 443)
        "--new",
        "--filter-tcp=2053,2083,2087,2096,8443",
        "--hostlist-domains=discord.media",
        *_EXCLUDE,
        *_hfs("www.google.com", "ts", 4),
        # 4. Google/YouTube группа - свой список, нулевой ip-id
        "--new",
        "--filter-tcp=443",
        "--hostlist={LISTS}list-google.txt",
        "--ip-id=zero",
        *_hfs("www.google.com", "ts", 4),
        # 5. Основной список (дискорд и прочее) 80+443
        "--new",
        "--filter-tcp=80,443",
        *_HOSTS,
        *_hfs("ozon.ru", "ts,md5sig", 4),
        # 6. ipset: QUIC по IP (заглушка, см. ipset-all.txt)
        "--new",
        "--filter-udp=443",
        "--ipset={LISTS}ipset-all.txt",
        *_EXCL_IPSET,
        *_QUIC_TECH_COMBO,
        # 7. ipset: TCP 80/443/8443 по IP (заглушка)
        "--new",
        "--filter-tcp=80,443,8443",
        "--ipset={LISTS}ipset-all.txt",
        *_EXCL_IPSET,
        *_hfs("ozon.ru", "ts", 4),
    ]


PRESETS: list[dict] = [
    {"name": "combo",         "args": _combo_chain()},
    {"name": "general",       "args": _chain("general", _tls_seqovl())},
    {"name": "fake",          "args": _chain("fake", _tls_fake())},
    {"name": "multisplit",    "args": _chain("multisplit", _tls_multisplit())},
    {"name": "disorder",      "args": _chain("disorder", _tls_disorder())},
    {"name": "disorder-fake", "args": _chain("disorder-fake", _tls_disorder_fake())},
    {"name": "hostfakesplit", "args": _chain("hostfakesplit", _tls_hostfakesplit())},
    {"name": "fakedsplit",    "args": _chain("fakedsplit", _tls_fakedsplit())},
    {"name": "headsplit",     "args": _chain("headsplit", _tls_headsplit())},
    {"name": "repeats",       "args": _chain("repeats", _tls_repeats())},
]
