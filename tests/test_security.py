# -*- coding: utf-8 -*-
"""Безопасность (01.10.2026, «фулл-защита»): пакет S1-S5.

S1 - DPAPI-шифрование подписки в state.json;
S2 - config.json живёт на диске лишь до старта движка (purge_config_file);
S3 - пиннинг SHA256 sing-box.exe перед запуском движка;
S4 - гигиена журнала: ни subUrl, ни креды нод не попадают в vpn-launcher.log;
S5 - kill switch: план фильтров WFP + аккуратный отказ (без админа/адресов).
"""
from __future__ import annotations

import ctypes
import json
import os
import types
import uuid
from pathlib import Path

import pytest

from vpn_launcher.core import config as cfg_mod
from vpn_launcher.core import state as state_mod
from vpn_launcher.core import subscription as sub_mod
from vpn_launcher.core.config import purge_config_file
from vpn_launcher.core.state import SUB_URL_PREFIX, load_state, save_state
from vpn_launcher.win import proc as proc_mod
from vpn_launcher.win import wfp as wfp_mod

SECRET_URL = "https://sub.example/SECRETTOKEN123abc"
SECRET_TOKEN = "SECRETTOKEN123abc"
SECRET_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SUB_BODY = f"vless://{SECRET_UUID}@h.example:443#node1"


# ---------------------------------------------------------------- S1: state --
class TestStateEncryption:
    def test_suburl_encrypted_at_rest(self, tmp_path):
        """subUrl на диске = dpapi1:<base64>, plaintext-ссылки нет."""
        p = tmp_path / "state.json"
        st = dict(state_mod.DEFAULT_STATE)
        st["subUrl"] = SECRET_URL
        save_state(st, p)

        raw = p.read_text(encoding="utf-8")
        assert SECRET_URL not in raw and SECRET_TOKEN not in raw
        data = json.loads(raw)
        assert data["subUrl"].startswith(SUB_URL_PREFIX)
        base64_part = data["subUrl"][len(SUB_URL_PREFIX):]
        assert base64_part and all(
            c.isalnum() or c in "+/=" for c in base64_part
        ), "значение - base64 после префикса"
        # и читается обратно тем же содержимым (DPAPI CurrentUser)
        assert load_state(p) == st

    def test_legacy_plaintext_migrates(self, tmp_path):
        """Старый PS-файл читается как раньше, шифруется при следующем save."""
        p = tmp_path / "state.json"
        p.write_text(
            json.dumps(dict(state_mod.DEFAULT_STATE, subUrl=SECRET_URL)),
            encoding="utf-8",
        )
        assert load_state(p)["subUrl"] == SECRET_URL  # миграция без потерь

        save_state(load_state(p), p)
        assert SECRET_URL not in p.read_text(encoding="utf-8")
        assert load_state(p)["subUrl"] == SECRET_URL

    def test_undecryptable_blob_yields_empty(self, tmp_path):
        """Чужой ПК/учётка: не падаем, подписка пустая + строка в логе."""
        p = tmp_path / "state.json"
        bad = SUB_URL_PREFIX + "bm90LWRwYXBpLWRhdGE"  # base64 от "not-dpapi-data"
        p.write_text(
            json.dumps(dict(state_mod.DEFAULT_STATE, subUrl=bad)),
            encoding="utf-8",
        )
        captured: list[str] = []
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(state_mod, "write_log", captured.append)
            assert load_state(p)["subUrl"] == ""
        assert captured and "расшифровалась" in captured[0]

    def test_other_fields_stay_plaintext(self, tmp_path):
        """Совместимость с PS-форматом: режим/списки - открытым JSON."""
        p = tmp_path / "state.json"
        st = dict(state_mod.DEFAULT_STATE)
        st.update(subUrl=SECRET_URL, mode="proxy", appList=["game.exe"])
        save_state(st, p)
        raw = json.loads(p.read_text(encoding="utf-8"))
        assert raw["mode"] == "proxy"
        assert raw["appList"] == ["game.exe"]
        assert raw["subUrl"] != SECRET_URL

    def test_double_save_not_reencrypted(self, tmp_path):
        """Уже шифрованное значение не шифруется повторно (нет «матрёшки»)."""
        p = tmp_path / "state.json"
        st = dict(state_mod.DEFAULT_STATE)
        st["subUrl"] = SECRET_URL
        save_state(st, p)
        save_state(load_state(p), p)
        raw = p.read_text(encoding="utf-8")
        assert raw.count(SUB_URL_PREFIX) == 1, "префикс ровно один"
        assert load_state(p)["subUrl"] == SECRET_URL


# ---------------------------------------------------------------- S2: config --
class TestConfigPurge:
    def test_purge_removes_existing(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text('{"x": 1}', encoding="utf-8")
        assert purge_config_file(p) is True
        assert not p.exists()

    def test_purge_missing_is_ok(self, tmp_path):
        assert purge_config_file(tmp_path / "nope.json") is True

    def test_purge_locked_retries_then_fails(self, tmp_path, monkeypatch):
        """Windows держит файл -> повторы, затем False + строка в логе."""
        p = tmp_path / "config.json"
        p.write_text("{}", encoding="utf-8")
        sleeps: list = []
        logs: list = []
        monkeypatch.setattr(
            Path, "unlink",
            lambda *a, **k: (_ for _ in ()).throw(PermissionError()),
        )
        # не трогаем глобальный time.sleep - подменяем модуль в cfg
        monkeypatch.setattr(
            cfg_mod, "time", type("T", (), {"sleep": staticmethod(sleeps.append)})
        )
        monkeypatch.setattr(cfg_mod, "write_log", logs.append)
        assert purge_config_file(p, retries=3, delay=0.01) is False
        assert sleeps == [0.01, 0.01, 0.01], "должен повторять, пока файл занят"
        assert logs and "config.json" in logs[0]
        assert p.exists(), "неудачный purge не удаляет файл"

    def test_connect_flows_use_purge_helper(self):
        """Проводка: window импортирует purge и вызывает после старта/рестарта."""
        import vpn_launcher.ui.window as win_mod

        assert win_mod.purge_config_file is purge_config_file
        src = Path(win_mod.__file__).read_text(encoding="utf-8")
        assert src.count("purge_config_file(") >= 4, (
            "ожидаются вызовы: старт приложения, коннект, рестарт, testcfg"
        )


# ---------------------------------------------------------------- S3: engine --
class TestEnginePinning:
    @pytest.mark.skipif(not proc_mod.SING_BOX.is_file(), reason="sing-box.exe нет в репо")
    def test_engine_hash_pinned_to_repo(self):
        """Константа = хэшу файла из репо (обновление движка = осознанный бамп)."""
        assert proc_mod.engine_hash(proc_mod.SING_BOX) == proc_mod.ENGINE_SHA256

    def test_verify_engine_ok(self, tmp_path, monkeypatch):
        exe = tmp_path / "sing-box.exe"
        exe.write_bytes(b"MZ-fake-engine")
        monkeypatch.setattr(
            proc_mod, "ENGINE_SHA256", proc_mod.engine_hash(exe)
        )
        proc_mod.verify_engine(exe)  # без исключения

    def test_verify_engine_mismatch_raises_and_logs(self, tmp_path, monkeypatch):
        exe = tmp_path / "sing-box.exe"
        exe.write_bytes(b"MZ-tampered")
        monkeypatch.setattr(proc_mod, "ENGINE_SHA256", "0" * 64)
        logs: list = []
        monkeypatch.setattr(proc_mod, "write_log", logs.append)
        with pytest.raises(OSError, match="повреждён или подменён"):
            proc_mod.verify_engine(exe)
        assert logs and "MISMATCH" in logs[0]
        assert len(logs[0]) < 200, "в лог не попадает лишнего"

    def test_verify_engine_missing_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            proc_mod.verify_engine(tmp_path / "absent.exe")

    def test_start_and_check_call_verify(self):
        """Проводка: и run, и check обязаны сверять хэш до exec."""
        import inspect

        import vpn_launcher.core.config as c

        assert "verify_engine()" in inspect.getsource(proc_mod.start_sing_box)
        assert "verify_engine(exe)" in inspect.getsource(c.test_sing_box_config)


# ------------------------------------------------------------- S4: log hygiene -
class _FakeHttpResp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return SUB_BODY.encode("utf-8")


def test_log_hygiene_no_secrets(monkeypatch, tmp_path):
    """S4: журнал не знает ни subUrl, ни uuid нод - только хост и счётчики."""
    captured: list[str] = []

    def capture(msg):
        captured.append(str(msg))

    monkeypatch.setattr(state_mod, "write_log", capture)
    monkeypatch.setattr(cfg_mod, "write_log", capture)
    monkeypatch.setattr(proc_mod, "write_log", capture)
    monkeypatch.setattr(sub_mod, "write_log", capture)

    # 1. состояние: сохранение/чтение с секретной подпиской
    st = dict(state_mod.DEFAULT_STATE)
    st["subUrl"] = SECRET_URL
    save_state(st, tmp_path / "state.json")
    assert load_state(tmp_path / "state.json") == st

    # 2. подписка: реальный путь логирования (host, не URL)
    monkeypatch.setattr(
        sub_mod.urllib.request, "urlopen", lambda *a, **k: _FakeHttpResp()
    )
    nodes = sub_mod.fetch_nodes(SECRET_URL, logger=capture)
    assert nodes and nodes[0]["uuid"] == SECRET_UUID

    # 3. сборка конфига (пишет 3 строки в журнал)
    cfg_mod.new_sing_box_config(
        nodes, mode="tun", path=tmp_path / "config.json"
    )

    # 4. отказ шифрования состояния тоже без секретов в тексте
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(state_mod, "_dpapi", lambda *a: None)
        save_state(st, tmp_path / "state2.json")

    joined = "\n".join(captured)
    assert captured, "ожидаемые строки журнала"
    assert SECRET_URL not in joined, "полный URL подписки в логе"
    assert SECRET_TOKEN not in joined, "токен подписки в логе"
    assert SECRET_UUID not in joined, "uuid ноды в логе"
    assert "sub.example" in joined, "хост подписки логируется (как в PS) - ок"


# ----------------------------------------------------------------- S5: wfp ----
class TestWfpStructs:
    def test_struct_sizes_match_sdk_x64(self):
        """Раскладки ctypes == раскладкам fwptypes/fwpmtypes под MSVC x64."""
        assert ctypes.sizeof(wfp_mod._COND_VALUE) == 16
        assert ctypes.sizeof(wfp_mod._VALUE) == 16
        assert ctypes.sizeof(wfp_mod._COND) == 40
        assert ctypes.sizeof(wfp_mod._ACTION) == 20
        assert ctypes.sizeof(wfp_mod._FILTER) == 200
        assert ctypes.sizeof(wfp_mod._SUBLAYER) == 72
        assert ctypes.sizeof(wfp_mod._SESSION) == 72
        assert wfp_mod._SESSION.flags.offset == 32  # после GUID+DISPLAY
        assert ctypes.sizeof(wfp_mod._V4AM) == 8
        assert ctypes.sizeof(wfp_mod._V6AM) == 17

    def test_v4_cidr_encoding_pinned(self):
        """Host-order UINT32 (эмпирика: иначе FWP_E_INVALID_NET_MASK)."""
        assert wfp_mod._cidr_v4("192.168.0.0/24") == (0xC0A80000, 0xFFFFFF00)
        assert wfp_mod._cidr_v4("10.0.0.0/8") == (0x0A000000, 0xFF000000)
        assert wfp_mod._cidr_v4("1.2.3.4/32") == (0x01020304, 0xFFFFFFFF)


class TestDynamicSession:
    """Сессия WFP - динамическая: объекты живут до её закрытия.

    Эмпирика 01.10.2026: сессия БЕЗ флага оставляла фильтры после close
    (112 «сирот», блокировавших чужой трафик), - флаг обязателен.
    """

    def test_flag_value_pinned(self):
        # fwpmtypes.h: DYNAMIC=0x1 (сверено по WireGuard/OpenVPN/windows-sys);
        # 0x2 - это RESERVED, «по памяти» был бы молчаливый баг.
        assert wfp_mod.FWPM_SESSION_FLAG_DYNAMIC == 0x00000001

    def test_open_engine_passes_dynamic_session(self, monkeypatch):
        seen: dict = {}

        def fake_open(server, authn, authid, sess_ptr, handle_ptr):
            seen["authn"] = authn
            seen["flags"] = sess_ptr._obj.flags  # byref -> _SESSION
            handle_ptr._obj.value = 4242
            return 0

        monkeypatch.setattr(
            wfp_mod, "_fwp", types.SimpleNamespace(FwpmEngineOpen0=fake_open)
        )
        handle = wfp_mod._open_engine()
        assert handle.value == 4242
        assert seen["authn"] == 10  # RPC_C_AUTHN_WINNT, затем DEFAULT не нужен
        assert seen["flags"] == wfp_mod.FWPM_SESSION_FLAG_DYNAMIC

    def test_open_engine_raises_when_denied(self, monkeypatch):
        monkeypatch.setattr(
            wfp_mod, "_fwp",
            types.SimpleNamespace(FwpmEngineOpen0=lambda *a: 5),  # ERROR_ACCESS_DENIED
        )
        with pytest.raises(OSError, match="rc=5"):
            wfp_mod._open_engine()


class TestWipeFilters:
    """Явное удаление фильтров по ключу: снятие + зачистка сирот."""

    def test_is_ours_by_name_or_sublayer(self):
        ours = uuid.UUID(wfp_mod.SUBLAYER_GUID)
        other = uuid.UUID("11111111-2222-3333-4444-555555555555")
        assert wfp_mod._is_ours("VPN Launcher kill switch", other)
        assert wfp_mod._is_ours("", ours)  # имя чужое, но саблэйл наш
        assert not wfp_mod._is_ours("Defender", other)
        assert not wfp_mod._is_ours(None, other)

    def test_wipe_deletes_every_our_key(self, monkeypatch):
        keys = [
            "aaaaaaaa-0000-0000-0000-000000000001",
            "aaaaaaaa-0000-0000-0000-000000000002",
        ]
        monkeypatch.setattr(wfp_mod, "_our_filter_keys", lambda h: list(keys))
        deleted: list = []

        def fake_del(handle, guid_ptr):  # byref(_GUID) -> _obj
            deleted.append(str(uuid.UUID(bytes_le=bytes(guid_ptr._obj))))
            return 0

        monkeypatch.setattr(wfp_mod._fwp, "FwpmFilterDeleteByKey0", fake_del)
        assert wfp_mod._wipe_our_filters("H1") == 2
        assert deleted == keys

    def test_wipe_skips_already_gone_keys(self, monkeypatch):
        """Промах удаления (фильтр исчез параллельно) - не фатален."""
        monkeypatch.setattr(
            wfp_mod, "_our_filter_keys",
            lambda h: ["bbbbbbbb-0000-0000-0000-000000000001"],
        )
        monkeypatch.setattr(wfp_mod._fwp, "FwpmFilterDeleteByKey0", lambda h, g: 6)
        assert wfp_mod._wipe_our_filters("H1") == 0

    def test_enum_failure_is_raised(self, monkeypatch):
        def boom(h):
            raise OSError("FwpmFilterCreateEnumHandle0 rc=0x5")

        monkeypatch.setattr(wfp_mod, "_our_filter_keys", boom)
        with pytest.raises(OSError, match="CreateEnumHandle"):
            wfp_mod._wipe_our_filters("H1")


class TestSelfExe:
    def test_self_exe_is_image_path(self):
        """Путь образа процесса, а не sys.executable (uv-venv: пере-экзекция).

        appid-матчинг WFP идёт по образу: по sys.executable процесс в selftest
        промахивался и ловил собственный блок (UAC-проба 30.09.2026).
        """
        exe = wfp_mod._self_exe()
        assert os.path.isabs(exe) and os.path.exists(exe)


class TestBuildSpecs:
    SPECS = wfp_mod.build_specs(
        r"C:\app\sing-box.exe", ["172.19.0.1/30", "fdfe::1/64"]
    )

    def test_block_exists_on_both_layers(self):
        blocks = [s for s in self.SPECS if s["action"] == wfp_mod.FWP_ACTION_BLOCK]
        assert {s["layer"] for s in blocks} == {
            wfp_mod.GUID_LAYER_V4,
            wfp_mod.GUID_LAYER_V6,
        }
        assert all(not s["conds"] for s in blocks), "блок - без условий"
        assert all(s["weight"] == wfp_mod.WEIGHT_BLOCK for s in blocks)

    def test_permits_outrank_block(self):
        permits = [s for s in self.SPECS if s["action"] == wfp_mod.FWP_ACTION_PERMIT]
        assert permits and all(
            s["weight"] > wfp_mod.WEIGHT_BLOCK for s in permits
        ), "веса permit > block - иначе порядок недетерминирован"

    def test_engine_appid_on_both_layers(self):
        appids = [
            s
            for s in self.SPECS
            if s["conds"] and s["conds"][0]["kind"] == "appid"
        ]
        assert len(appids) == 2
        assert {s["layer"] for s in appids} == {
            wfp_mod.GUID_LAYER_V4,
            wfp_mod.GUID_LAYER_V6,
        }
        assert appids[0]["conds"][0]["value"] == r"C:\app\sing-box.exe"

    def test_tun_local_addresses(self):
        local = {
            (s["layer"], s["conds"][0]["value"])
            for s in self.SPECS
            if s["conds"] and s["conds"][0]["field"] == wfp_mod.GUID_COND_LOCAL
        }
        assert local == {
            (wfp_mod.GUID_LAYER_V4, "172.19.0.1/30"),
            (wfp_mod.GUID_LAYER_V6, "fdfe::1/64"),
        }

    def test_lan_and_loopback_permit(self):
        remote = {
            s["conds"][0]["value"]
            for s in self.SPECS
            if s["conds"] and s["conds"][0]["field"] == wfp_mod.GUID_COND_REMOTE
        }
        for cidr in ("192.168.0.0/16", "127.0.0.0/8", "224.0.0.0/4", "fe80::/10", "::1/128"):
            assert cidr in remote

    def test_total_count(self):
        # 2 tun-адреса + 2 appid + 7 LAN v4 + 4 LAN v6 + 2 блока
        assert len(self.SPECS) == 17


class TestBuildSpecsIncludeMode:
    """02.10.2026: include инвертирует kill switch - глобального блока нет.

    Блокируются ТОЛЬКО выбранные образы: при падении движка они не утекают
    на прямую, а все остальные приложения работают без ограничений.
    """

    PATHS = [r"C:\x\msedge.exe", r"C:\x\Discord.exe"]
    SPECS = wfp_mod.build_specs(
        r"C:\app\sing-box.exe", ["172.19.0.1/30"],
        app_mode="include", app_paths=PATHS,
    )
    BLOCKS = [s for s in SPECS if s["action"] == wfp_mod.FWP_ACTION_BLOCK]

    def test_no_unconditional_block(self):
        assert self.BLOCKS, "блоки выбранных образов обязательны"
        assert all(
            s["conds"] and s["conds"][0]["kind"] == "appid" for s in self.BLOCKS
        ), "в include нет глобального блока - только appid выбранных"

    def test_block_selected_on_both_layers(self):
        got = {(s["layer"], s["conds"][0]["value"]) for s in self.BLOCKS}
        expected = {
            (layer, path)
            for path in self.PATHS
            for layer in (wfp_mod.GUID_LAYER_V4, wfp_mod.GUID_LAYER_V6)
        }
        assert got == expected
        assert all(s["weight"] == wfp_mod.WEIGHT_BLOCK for s in self.BLOCKS)

    def test_engine_tun_lan_still_permit(self):
        permits = [s for s in self.SPECS if s["action"] == wfp_mod.FWP_ACTION_PERMIT]
        assert permits and all(
            s["weight"] > wfp_mod.WEIGHT_BLOCK for s in permits
        ), "разрешения обязаны перебивать блоки выбранных"
        assert any(
            s["conds"] and s["conds"][0]["kind"] == "appid"
            and s["conds"][0]["value"] == r"C:\app\sing-box.exe"
            for s in permits
        ), "движок разрешён"
        assert any(
            s["conds"] and s["conds"][0]["field"] == wfp_mod.GUID_COND_LOCAL
            for s in permits
        ), "туннель разрешён"
        assert any(
            s["conds"] and s["conds"][0]["field"] == wfp_mod.GUID_COND_REMOTE
            for s in permits
        ), "LAN разрешён"

    def test_empty_list_keeps_connection_open(self):
        specs = wfp_mod.build_specs(
            r"C:\app\sing-box.exe", ["172.19.0.1/30"], app_mode="include"
        )
        assert not [
            s for s in specs if s["action"] == wfp_mod.FWP_ACTION_BLOCK
        ], "пустой include = блокировать некого, все работают напрямую"


class TestBuildSpecsExcludeAppPermits:
    """exclude: permit образов «мимо VPN» перебивает глобальный блок."""

    PATH = r"C:\games\cs2.exe"
    SPECS = wfp_mod.build_specs(
        r"C:\app\sing-box.exe", ["172.19.0.1/30"],
        app_mode="exclude", app_paths=[PATH],
    )

    def test_unconditional_block_still_present(self):
        blocks = [s for s in self.SPECS if s["action"] == wfp_mod.FWP_ACTION_BLOCK]
        assert any(not s["conds"] for s in blocks), (
            "классика: глобальный блок остаётся"
        )

    def test_appid_permits_outrank_block(self):
        permits = [
            s for s in self.SPECS
            if s["action"] == wfp_mod.FWP_ACTION_PERMIT
            and s["conds"] and s["conds"][0]["kind"] == "appid"
            and s["conds"][0]["value"] == self.PATH
        ]
        assert {s["layer"] for s in permits} == {
            wfp_mod.GUID_LAYER_V4,
            wfp_mod.GUID_LAYER_V6,
        }
        assert all(s["weight"] == wfp_mod.WEIGHT_PERMIT for s in permits)
        blocks = [s for s in self.SPECS if s["action"] == wfp_mod.FWP_ACTION_BLOCK]
        assert all(s["weight"] < wfp_mod.WEIGHT_PERMIT for s in blocks), (
            "permit образа должен перебивать глобальный блок по весу"
        )


class TestResolveImagePaths:
    """Имена «Discord.exe» -> пути образов для appid-условий WFP."""

    @staticmethod
    def _flat_sources(monkeypatch, running=(), roots=(), which=None):
        monkeypatch.setattr(wfp_mod, "_running_images", lambda names: list(running))
        monkeypatch.setattr(wfp_mod, "_app_paths_candidates", lambda name: [])
        monkeypatch.setattr(wfp_mod, "_root_candidates", lambda name: list(roots))
        monkeypatch.setattr(wfp_mod.shutil, "which", lambda name: which)

    def test_abs_existing_path(self, monkeypatch, tmp_path):
        self._flat_sources(monkeypatch)
        exe = tmp_path / "game.exe"
        exe.write_text("x", encoding="utf-8")
        assert wfp_mod.resolve_image_paths([str(exe)]) == [str(exe)]

    def test_missing_name_skipped_and_logged(self, monkeypatch):
        self._flat_sources(monkeypatch)
        logs: list = []
        monkeypatch.setattr(wfp_mod, "write_log", logs.append)
        assert wfp_mod.resolve_image_paths(["ghost.exe"]) == []
        assert logs and "ghost.exe" in logs[0]

    def test_sources_deduped(self, monkeypatch, tmp_path):
        exe = tmp_path / "Discord.exe"
        exe.write_text("x", encoding="utf-8")
        self._flat_sources(
            monkeypatch, running=[str(exe)], roots=[str(exe)], which=str(exe)
        )
        assert wfp_mod.resolve_image_paths(["Discord.exe"]) == [str(exe)]

    def test_empty_list_touches_no_sources(self, monkeypatch):
        monkeypatch.setattr(
            wfp_mod,
            "_running_images",
            lambda names: (_ for _ in ()).throw(AssertionError("не вызывается")),
        )
        assert wfp_mod.resolve_image_paths([]) == []


class TestInstallLifecycle:
    @pytest.fixture(autouse=True)
    def _clean_session(self, monkeypatch):
        """Каждый тест - с чистым состоянием сессии WFP."""
        monkeypatch.setattr(wfp_mod, "_ENGINE", None)

    def test_install_passes_mode_and_resolved_paths(self, monkeypatch):
        """02.10.2026: install пробрасывает app_mode и резолвит образы."""
        seen: dict = {}
        monkeypatch.setattr(wfp_mod, "_open_engine", lambda: "H1")
        monkeypatch.setattr(wfp_mod, "_wipe_our_filters", lambda h: 0)
        monkeypatch.setattr(wfp_mod, "_add_sublayer", lambda h: None)
        monkeypatch.setattr(
            wfp_mod,
            "resolve_image_paths",
            lambda names: [r"C:\x\a.exe"] if names else [],
        )
        monkeypatch.setattr(
            wfp_mod, "build_specs", lambda exe, addrs, **k: seen.update(k) or []
        )
        monkeypatch.setattr(wfp_mod, "_add_filters", lambda h, specs: len(specs))
        monkeypatch.setattr(wfp_mod, "write_log", lambda m: None)
        monkeypatch.setattr(wfp_mod._fwp, "FwpmEngineClose0", lambda h: 0)
        try:
            ok = wfp_mod.install_kill_switch(
                ["172.19.0.1/30"],
                app_mode="include",
                app_names=["a.exe"],
            )
        finally:
            wfp_mod.remove_kill_switch()
        assert ok is True
        assert seen["app_mode"] == "include"
        assert seen["app_paths"] == [r"C:\x\a.exe"]

    def test_empty_addrs_refused_without_opening_wfp(self, monkeypatch):
        logs: list = []
        monkeypatch.setattr(wfp_mod, "write_log", logs.append)

        def boom():
            raise AssertionError("WFP не должен открываться")

        monkeypatch.setattr(wfp_mod, "_open_engine", boom)
        assert wfp_mod.install_kill_switch([]) is False
        assert logs and "адреса TUN" in logs[0]

    def test_denied_reports_false_without_exception(self, monkeypatch):
        logs: list = []
        monkeypatch.setattr(wfp_mod, "write_log", logs.append)
        monkeypatch.setattr(
            wfp_mod,
            "_open_engine",
            lambda: (_ for _ in ()).throw(OSError("FwpmEngineOpen0 rc=5")),
        )
        assert wfp_mod.install_kill_switch(["172.19.0.1/30"]) is False
        assert wfp_mod._ENGINE is None
        assert logs and "WFP недоступен" in logs[0]

    def test_rollback_on_install_error(self, monkeypatch):
        closed: list = []
        order: list = []
        monkeypatch.setattr(wfp_mod._fwp, "FwpmEngineClose0", closed.append)
        monkeypatch.setattr(wfp_mod, "write_log", lambda m: None)
        monkeypatch.setattr(wfp_mod, "_open_engine", lambda: "FAKE-HANDLE")
        monkeypatch.setattr(
            wfp_mod, "_wipe_our_filters",
            lambda h: order.append("wipe") or 0,
        )
        monkeypatch.setattr(
            wfp_mod, "_add_sublayer",
            lambda h: (_ for _ in ()).throw(OSError("FwpmSubLayerAdd0 rc=5")),
        )
        assert wfp_mod.install_kill_switch(["172.19.0.1/30"]) is False
        assert closed == ["FAKE-HANDLE"], "сбой установки = закрыть сессию (откат)"
        assert order == ["wipe"], "зачистка сирот идёт ДО добавления фильтров"
        assert wfp_mod._ENGINE is None

    def test_success_idempotent_and_remove(self, monkeypatch):
        closed: list = []
        added: list = []
        wiped: list = []
        monkeypatch.setattr(wfp_mod._fwp, "FwpmEngineClose0", lambda h: closed.append(h) or 0)
        monkeypatch.setattr(wfp_mod, "write_log", lambda m: None)
        monkeypatch.setattr(wfp_mod, "_open_engine", lambda: "H1")
        monkeypatch.setattr(wfp_mod, "_wipe_our_filters", lambda h: wiped.append(h) or 0)
        monkeypatch.setattr(wfp_mod, "_add_sublayer", lambda h: None)
        monkeypatch.setattr(
            wfp_mod, "_add_filters",
            lambda h, specs: added.append(len(specs)) or len(specs),
        )
        assert wfp_mod.install_kill_switch(["172.19.0.1/30"]) is True
        assert wfp_mod.is_active() is True
        # повторный вызов - не открывает вторую сессию
        assert wfp_mod.install_kill_switch(["172.19.0.1/30"]) is True
        assert added == [16], "1 tun + 2 appid + 7 LAN v4 + 4 LAN v6 + 2 блока"
        wfp_mod.remove_kill_switch()
        assert wfp_mod.is_active() is False
        assert closed == ["H1"]
        assert wiped == ["H1", "H1"], "wipe и при установке, и при снятии (по ключу)"
        wfp_mod.remove_kill_switch()  # идемпотентно, без исключений
        assert wiped == ["H1", "H1"], "повторное снятие - не открывает WFP"

    def test_remove_without_session_is_noop(self, monkeypatch):
        closed: list = []
        monkeypatch.setattr(wfp_mod._fwp, "FwpmEngineClose0", closed.append)
        monkeypatch.setattr(wfp_mod, "_ENGINE", None)
        wfp_mod.remove_kill_switch()
        assert closed == []
