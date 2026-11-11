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

v5 (31.10.2026) - ALT11/ALT13 ИЗ ПАКЕТА 1.10.4 (ПОИСК РАБОЧИХ):
  Жалоба 31.10: «нажимал кнопку DPI, но видимо не нашёлся рабочий
  алгоритм». combo (реплика ALT9) на части сетей не справляется -
  добавили две свежие стратегии из zapret-discord-youtube 1.10.4
  (20.10.2026), стоящие сразу после combo: alt11 (fake+multisplit c
  seqovl-наложением 664/681 и фейками sferum/stun2) и alt13
  (hostfakesplit с подменой хоста на mail.ru/www.google.com и фейками
  sochi_park/stun2). По 7 профилей каждая (GameFilter-профили пакета
  убраны: игры у нас идут через VPN/sing-box, им нужен свой winws).
  Фейки .bin скопированы из пакета байт-в-байт (хэши в VERSION.txt).

v6 (11.11.2026) - НОВЫЕ АЛГОРИТМЫ ПОД ИНЦИДЕНТ DISCORD 08-10.11.2026:
  Массовые таймауты DiscordMain/DiscordUpdates/DiscordCDN и вечное RTC
  на всех батниках 1.10.3/1.10.4 (issue Flowseal #18742, #18712); часть
  сетей спасает смена DNS, единичный подтверждённый успех - general
  (ALT2). Добавлены 4 стратегии, которых у нас не было:
    alt2    - multisplit + seqovl 652/split-pos 2 (тот самый ALT2);
    autotls - fake+multisplit seqovl 681 + fooling=ts, а фейк TLS не из
              .bin, а автогенерация из РЕАЛЬНОГО ClientHello
              (fake-tls-mod=rnd,dupsid,sni) - обходит DPI, выучивший
              старые фейковые отпечатки;
    badseq  - fake+multisplit с fooling=badseq и badseq-increment=1000
              (ALT4): другой тип порчи фейка, не badsum/ts;
    syndata - syndata+multidisorder по SYN (ALT5), без хостлистов: ловит
              весь TCP-80/443/8443 независимо от SNI, когда DPI режет
              ещё до ClientHello.
  Пробы расширены под инцидент: updates.discord.com (DiscordUpdates),
  i.ytimg.com (превью) и redirector.googlevideo.com (видеопоток).

v4 (12.10.2026) - ФИКС ДЕМОК ЭКРАНА (Discord, ошибка 1007):
  Часть демонстраций экрана не грузилась с combo, хотя ALT9 грузил.
  Два расхождения с эталоном найдены и выровнены: (1) fake-файлы были
  СВОИ (gen_payloads), а не эталонные zapret-discord
  quic_initial_www_google_com.bin / ACTIVE_DISCORD_UDP.bin - скопированы
  из рабочего пакета и подключены (хэши в zapret/VERSION.txt, исходный
  пакет не менялся); (2) в QUIC- и основном профилях не было
  --ipset-exclude, как в ALT9 - добавлены. Списки проверены построчно:
  наши - супермножество эталона, user-файлы - заглушки в обеих сторонах.

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
# v4 (12.10.2026): QUIC/голос-фейки = ЭТАЛОННЫЕ файлы zapret-discord
# (с ними у пользователя грузились демки экрана, ошибка 1007); свои
# gen_payloads-фейки давали мимо. Хэши - в zapret/VERSION.txt.
_FAKE_QUIC = "+0@{BIN}quic_initial_www_google_com.bin"
_FAKE_DISCORD = "+0@{BIN}ACTIVE_DISCORD_UDP.bin"
# v5 (31.10.2026): эталонные фейки пакета zapret-discord-youtube 1.10.4
# для стратегий alt11/alt13; скопированы байт-в-байт (хэши в VERSION.txt)
_FAKE_GGLE = "+0@{BIN}tls_clienthello_www_google_com.bin"   # ClientHello google.com (681B)
_FAKE_SFERUM = "+0@{BIN}tls_clienthello_www_sferum_ru.bin"  # ClientHello sferum.ru (661B)
_FAKE_SOCHI = "+0@{BIN}tls_clienthello_sochi_park.bin"      # ClientHello sochi-park (244B)
_FAKE_STUN2 = "+0@{BIN}stun2.bin"                           # STUN-пакет (120B)
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
    f"--dpi-desync-fake-stun={_FAKE_DISCORD}",  # в ALT9 оба фейка = ACTIVE
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

# только ipset-exclude - для профилей с хост-списками (как в ALT9)
_IPSET_EXCL = (
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
        *_IPSET_EXCL,  # ipset-exclude и здесь - как в ALT9 (v4)
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
        *_IPSET_EXCL,  # как в ALT9 (v4)
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


# --- v5 (31.10.2026): реплики zapret-discord-youtube 1.10.4 ---------------
# Источник: батники general (ALT11).bat / general (ALT13).bat рабочего
# пакета 1.10.4 (20.10.2026). Копируем ПРОФИЛЬ-В-ПРОФИЛЬ, кроме
# GameFilter-профилей пакета (игры у нас идут через VPN/sing-box - им
# нужен свой winws). Фейки .bin скопированы из пакета байт-в-байт
# (хэши - в zapret/VERSION.txt).

# QUIC в alt11/alt13: repeats=11 (в комбо - 6), тот же эталонный фейк
_QUIC_TECH_ALT = (
    "--dpi-desync=fake",
    "--dpi-desync-repeats=11",
    f"--dpi-desync-fake-quic={_FAKE_QUIC}",
)


def _alt11_chain() -> list[str]:
    """alt11 = реплика «general (ALT11)» пакета 1.10.4 (7 профилей).

    Отличия от combo: QUIC с repeats=11; медиа/гугл на fake+multisplit
    c seqovl-наложением 681 и фейком ClientHello google.com; основной
    профиль на seqovl 664 с ДВОЙНЫМ фейком (stun2 + sferum) и
    fake-http; голос как в combo. Источник аргументов - сам батник
    (см. докстринг модуля, v5)."""
    media_google_tech = (
        "--dpi-desync=fake,multisplit",
        "--dpi-desync-split-seqovl=681",
        "--dpi-desync-split-pos=1",
        "--dpi-desync-fooling=ts",
        "--dpi-desync-repeats=8",
        f"--dpi-desync-split-seqovl-pattern={_FAKE_GGLE}",
        f"--dpi-desync-fake-tls={_FAKE_GGLE}",
    )
    main_tech = (
        "--dpi-desync=fake,multisplit",
        "--dpi-desync-split-seqovl=664",
        "--dpi-desync-split-pos=1",
        "--dpi-desync-fooling=ts",
        "--dpi-desync-repeats=8",
        f"--dpi-desync-split-seqovl-pattern={_FAKE_SFERUM}",
        f"--dpi-desync-fake-tls={_FAKE_STUN2}",
        f"--dpi-desync-fake-tls={_FAKE_SFERUM}",
        f"--dpi-desync-fake-http={_FAKE_SFERUM}",
    )
    return [
        "--comment=vpl-alt11",
        *_WF,
        # 1. QUIC 443 (HTTP/3: youtube и все h3-хосты списка)
        "--filter-udp=443",
        *_HOSTS,
        *_IPSET_EXCL,
        *_QUIC_TECH_ALT,
        # 2. Discord-голос / STUN (звонки)
        "--new",
        "--filter-udp=19294-19344,50000-50100",
        "--filter-l7=discord,stun",
        *_VOICE_TECH_COMBO,  # в ALT11 голос = комбо (repeats=6)
        # 3. discord.media на альт-портах (стримы/звонки не на 443)
        "--new",
        "--filter-tcp=2053,2083,2087,2096,8443",
        "--hostlist-domains=discord.media",
        *media_google_tech,
        # 4. Google/YouTube группа - свой список, нулевой ip-id
        "--new",
        "--filter-tcp=443",
        "--hostlist={LISTS}list-google.txt",
        "--ip-id=zero",
        *media_google_tech,
        # 5. Основной список (дискорд и прочее) 80+443
        "--new",
        "--filter-tcp=80,443",
        *_HOSTS,
        *_IPSET_EXCL,
        *main_tech,
        # 6. ipset: QUIC по IP (заглушка, см. ipset-all.txt)
        "--new",
        "--filter-udp=443",
        "--ipset={LISTS}ipset-all.txt",
        *_EXCL_IPSET,
        *_QUIC_TECH_ALT,
        # 7. ipset: TCP 80/443/8443 по IP (заглушка)
        "--new",
        "--filter-tcp=80,443,8443",
        "--ipset={LISTS}ipset-all.txt",
        *_EXCL_IPSET,
        *main_tech,
    ]


def _alt13_chain() -> list[str]:
    """alt13 = реплика «general (ALT13)» пакета 1.10.4 (7 профилей).

    Отличия от alt11: гугл на hostfakesplit (без ip-id), основной
    профиль на fake+hostfakesplit с подменой хоста на mail.ru и фейками
    sochi_park/stun2 (repeats=5), голос repeats=5, медиа repeats=7.
    Источник аргументов - сам батник (см. докстринг модуля, v5)."""
    media_tech = (
        "--dpi-desync=fake,multisplit",
        "--dpi-desync-split-seqovl=681",
        "--dpi-desync-split-pos=1",
        "--dpi-desync-fooling=ts",
        "--dpi-desync-repeats=7",
        f"--dpi-desync-split-seqovl-pattern={_FAKE_GGLE}",
        f"--dpi-desync-fake-tls={_FAKE_GGLE}",
    )
    google_tech = (
        "--dpi-desync=hostfakesplit",
        "--dpi-desync-fooling=ts",
        "--dpi-desync-hostfakesplit-mod=host=www.google.com",
    )
    main_tech = (
        "--dpi-desync=fake,hostfakesplit",
        "--dpi-desync-fooling=ts",
        "--dpi-desync-hostfakesplit-mod=host=mail.ru,altorder=1",
        "--dpi-desync-repeats=5",
        f"--dpi-desync-fake-tls={_FAKE_SOCHI}",
        f"--dpi-desync-fake-tls={_FAKE_STUN2}",
        f"--dpi-desync-fake-http={_FAKE_SOCHI}",
    )
    voice_tech = (
        "--dpi-desync=fake",
        "--dpi-desync-repeats=5",
        f"--dpi-desync-fake-discord={_FAKE_DISCORD}",
        f"--dpi-desync-fake-stun={_FAKE_DISCORD}",
    )
    return [
        "--comment=vpl-alt13",
        *_WF,
        # 1. QUIC 443 (HTTP/3)
        "--filter-udp=443",
        *_HOSTS,
        *_IPSET_EXCL,
        *_QUIC_TECH_ALT,
        # 2. Discord-голос / STUN (звонки)
        "--new",
        "--filter-udp=19294-19344,50000-50100",
        "--filter-l7=discord,stun",
        *voice_tech,
        # 3. discord.media на альт-портах
        "--new",
        "--filter-tcp=2053,2083,2087,2096,8443",
        "--hostlist-domains=discord.media",
        *media_tech,
        # 4. Google/YouTube группа - свой список
        "--new",
        "--filter-tcp=443",
        "--hostlist={LISTS}list-google.txt",
        *google_tech,
        # 5. Основной список (дискорд и прочее) 80+443
        "--new",
        "--filter-tcp=80,443",
        *_HOSTS,
        *_IPSET_EXCL,
        *main_tech,
        # 6. ipset: QUIC по IP (заглушка)
        "--new",
        "--filter-udp=443",
        "--ipset={LISTS}ipset-all.txt",
        *_EXCL_IPSET,
        *_QUIC_TECH_ALT,
        # 7. ipset: TCP 80/443/8443 по IP (заглушка)
        "--new",
        "--filter-tcp=80,443,8443",
        "--ipset={LISTS}ipset-all.txt",
        *_EXCL_IPSET,
        *main_tech,
    ]


# --- v6 (11.11.2026): стратегии под инцидент Discord 08-10.11.2026 --------
# Источник: батники general (ALT2)/(ALT4)/(ALT5)/(FAKE TLS AUTO ALT3)
# пакета zapret-discord-youtube 1.10.4. Отличие от прежних реплик: у этих
# стратегий разные точки вмешательства (seqovl 652, автогенерация фейка из
# реального ClientHello, badseq, SYN-данные), а не очередная перестановка
# badsum/ts. GameFilter-профили пакета по-прежнему не нужны (игры идут
# через VPN/sing-box).

# seqovl 652 со сдвигом split-pos=2 (ALT2; подтверждён в issue 10.11)
def _tls_seqovl652() -> tuple[str, ...]:
    return (
        "--dpi-desync=multisplit",
        "--dpi-desync-split-seqovl=652",
        "--dpi-desync-split-pos=2",
        f"--dpi-desync-split-seqovl-pattern={_FAKE_GGLE}",
    )


# fake + multisplit, но фейк TLS генерируется из РЕАЛЬНОГО ClientHello
# (fake-tls-mod без --dpi-desync-fake-tls): так DPI не узнаёт старый
# фейковый отпечаток из .bin
def _tls_autotls() -> tuple[str, ...]:
    return (
        "--dpi-desync=fake,multisplit",
        "--dpi-desync-split-seqovl=681",
        "--dpi-desync-split-pos=1",
        "--dpi-desync-fooling=ts",
        "--dpi-desync-repeats=8",
        f"--dpi-desync-split-seqovl-pattern={_FAKE_GGLE}",
        "--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com",
    )


# fake + multisplit с fooling=badseq и явным шагом (ALT4): DPI видит фейк
# с неверным seq и принимает его за реальный сегмент
def _tls_badseq() -> tuple[str, ...]:
    return (
        "--dpi-desync=fake,multisplit",
        "--dpi-desync-repeats=6",
        "--dpi-desync-fooling=badseq",
        "--dpi-desync-badseq-increment=1000",
        f"--dpi-desync-fake-tls={_FAKE_GGLE}",
    )


# SYN-данные + переупорядочивание: вмешательство до TLS-хендшейка, поэтому
# не зависит от SNI/хостлистов (ALT5)
_SYNDATA_TECH = ("--dpi-desync=syndata,multidisorder",)


def _suite(
    name: str,
    *,
    quic: tuple[str, ...],
    voice: tuple[str, ...],
    media: tuple[str, ...],
    google: tuple[str, ...],
    main: tuple[str, ...],
    google_ipid: bool = True,
) -> list[str]:
    """Семь самодостаточных профилей как у combo/alt11/alt13.

    Нужен, чтобы новые стратегии повторяли структуру исходных батников
    1.10.4 (QUIC, голос, медиа-альт-порты, google-группа, основной список,
    два ipset-профиля), а не только TLS-профиль.
    """
    return [
        f"--comment=vpl-{name}",
        *_WF,
        # 1. QUIC 443
        "--filter-udp=443",
        "--filter-l7=quic",
        *_HOSTS,
        *_IPSET_EXCL,
        *quic,
        # 2. Discord-голос / STUN
        "--new",
        "--filter-udp=19294-19344,50000-50100",
        "--filter-l7=discord,stun",
        *voice,
        # 3. discord.media на альт-портах
        "--new",
        "--filter-tcp=2053,2083,2087,2096,8443",
        "--hostlist-domains=discord.media",
        *_EXCLUDE,
        *media,
        # 4. Google/YouTube группа
        "--new",
        "--filter-tcp=443",
        "--hostlist={LISTS}list-google.txt",
        *(["--ip-id=zero"] if google_ipid else []),
        *google,
        # 5. Основной список (дискорд и прочее) 80+443
        "--new",
        "--filter-tcp=80,443",
        *_HOSTS,
        *_IPSET_EXCL,
        *main,
        # 6. ipset: QUIC по IP
        "--new",
        "--filter-udp=443",
        "--ipset={LISTS}ipset-all.txt",
        *_EXCL_IPSET,
        *quic,
        # 7. ipset: TCP 80/443/8443 по IP
        "--new",
        "--filter-tcp=80,443,8443",
        "--ipset={LISTS}ipset-all.txt",
        *_EXCL_IPSET,
        *main,
    ]


def _alt2_chain() -> list[str]:
    """alt2 = реплика «general (ALT2)» 1.10.4: seqovl 652 / split-pos 2.

    Единственная стратегия, которую 10.11.2026 подтвердил живой
    пользователь (вместе с ipset и GameFilter). Без фейков вообще -
    только наложение последовательностей."""
    return _suite(
        "alt2",
        quic=_QUIC_TECH_COMBO,
        voice=_VOICE_TECH_COMBO,
        media=_tls_seqovl652(),
        google=_tls_seqovl652(),
        main=_tls_seqovl652(),
    )


def _autotls_chain() -> list[str]:
    """autotls = реплика «general (FAKE TLS AUTO ALT3)» 1.10.4.

    Отличие от alt11: фейк TLS не подставляется из файла, а собирается
    winws из реального ClientHello (rnd,dupsid,sni=www.google.com)."""
    main = _tls_autotls() + (f"--dpi-desync-fake-http={_FAKE_SFERUM}",)
    return _suite(
        "autotls",
        quic=_QUIC_TECH_ALT,
        voice=_VOICE_TECH_COMBO,
        media=_tls_autotls(),
        google=_tls_autotls(),
        main=main,
    )


def _badseq_chain() -> list[str]:
    """badseq = реплика «general (ALT4)» 1.10.4.

    fooling=badseq с шагом 1000 вместо badsum/ts: фейк уходит с заведомо
    неверным seq, и DPI склеивает поток неверно."""
    main = _tls_badseq() + (
        f"--dpi-desync-fake-tls={_FAKE_STUN2}",
        f"--dpi-desync-fake-http={_FAKE_SFERUM}",
    )
    return _suite(
        "badseq",
        quic=_QUIC_TECH_COMBO,
        voice=_VOICE_TECH_COMBO,
        media=_tls_badseq(),
        google=_tls_badseq(),
        main=main,
    )


def _syndata_chain() -> list[str]:
    """syndata = реплика «general (ALT5)» 1.10.4 (без GameFilter-профиля).

    syndata,multidisorder по SYN на весь TCP 80/443/8443 и IPv4: работает
    даже там, где DPI блокирует до отправки ClientHello и хостлисты
    бесполезны. ipset-профиль идёт раньше общего, чтобы не дублировать
    обработку адресов из ipset-all.txt."""
    return [
        "--comment=vpl-syndata",
        *_WF,
        # 1. QUIC 443
        "--filter-udp=443",
        "--filter-l7=quic",
        *_HOSTS,
        *_IPSET_EXCL,
        *_QUIC_TECH_COMBO,
        # 2. Discord-голос / STUN
        "--new",
        "--filter-udp=19294-19344,50000-50100",
        "--filter-l7=discord,stun",
        *_VOICE_TECH_COMBO,
        # 3. ipset: TCP по IP
        "--new",
        "--filter-tcp=80,443,8443",
        "--ipset={LISTS}ipset-all.txt",
        *_EXCL_IPSET,
        *_SYNDATA_TECH,
        # 4. ВЕСЬ IPv4 TCP 80/443 (+альт-порты): без хостлистов
        "--new",
        "--filter-l3=ipv4",
        "--filter-tcp=80,443,2053,2083,2087,2096,8443",
        *_IPSET_EXCL,
        *_SYNDATA_TECH,
        # 5. ipset: QUIC по IP
        "--new",
        "--filter-udp=443",
        "--ipset={LISTS}ipset-all.txt",
        *_EXCL_IPSET,
        *_QUIC_TECH_COMBO,
    ]


PRESETS: list[dict] = [
    {"name": "combo",         "args": _combo_chain()},
    {"name": "alt2",          "args": _alt2_chain()},
    {"name": "autotls",       "args": _autotls_chain()},
    {"name": "badseq",        "args": _badseq_chain()},
    {"name": "alt11",         "args": _alt11_chain()},
    {"name": "alt13",         "args": _alt13_chain()},
    {"name": "general",       "args": _chain("general", _tls_seqovl())},
    {"name": "fake",          "args": _chain("fake", _tls_fake())},
    {"name": "multisplit",    "args": _chain("multisplit", _tls_multisplit())},
    {"name": "disorder",      "args": _chain("disorder", _tls_disorder())},
    {"name": "disorder-fake", "args": _chain("disorder-fake", _tls_disorder_fake())},
    {"name": "hostfakesplit", "args": _chain("hostfakesplit", _tls_hostfakesplit())},
    {"name": "fakedsplit",    "args": _chain("fakedsplit", _tls_fakedsplit())},
    {"name": "headsplit",     "args": _chain("headsplit", _tls_headsplit())},
    {"name": "repeats",       "args": _chain("repeats", _tls_repeats())},
    # v6: самый инвазивный (SYN-данные на весь IPv4 TCP) - последним,
    # чтобы обычные сайты не ломались, пока подбираются мягкие стратегии
    {"name": "syndata",       "args": _syndata_chain()},
]
