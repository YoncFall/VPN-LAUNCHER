# -*- coding: utf-8 -*-
"""Генерация ключей приёмника диагностики (X25519).

Приватный ключ НИКОГДА не попадает в репозиторий и в сборку приложения:
он лежит в профиле владельца и читается только приёмником
(tools/receiver/diag_receiver.py). Публичный ключ зашивается в приложение
(vpn_launcher/core/diag_key.py) - им отчёты только ШИФРУЮТСЯ.

Запуск (из корня vpn-launcher-py):
    .\\venv\\Scripts\\python.exe tools\\receiver\\gen_keys.py

Флаги:
    --private <путь>   куда положить приватный ключ
                       (по умолчанию %LOCALAPPDATA%\\VPN-LAUNCHER-RECEIVER\\receiver_key.json)
    --write-module     перезаписать vpn_launcher/core/diag_key.py публичным ключом
    --force            перезаписать существующий приватный ключ (старые отчёты
                       перестанут расшифровываться - не делать без нужды)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

DEFAULT_PRIVATE = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    / "VPN-LAUNCHER-RECEIVER"
    / "receiver_key.json"
)
MODULE = Path(__file__).resolve().parents[2] / "vpn_launcher" / "core" / "diag_key.py"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _restrict_acl(path: Path) -> None:
    """Windows: доступ к приватному ключу только текущему пользователю.

    icacls /inheritance:r снимает наследование, /grant:r даёт полный доступ
    ровно одному SID (текущему). На не-Windows - chmod 600.
    """
    if sys.platform == "win32":
        user = os.environ.get("USERNAME") or ""
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True,
            check=False,
            creationflags=0x08000000,
        )
    else:
        path.chmod(0o600)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ключи приёмника диагностики")
    ap.add_argument("--private", default=str(DEFAULT_PRIVATE))
    ap.add_argument("--write-module", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    dest = Path(args.private)
    if dest.exists() and not args.force:
        data = json.loads(dest.read_text(encoding="utf-8"))
        pub = data.get("publicKey") or ""
        if not pub:
            print("в файле нет publicKey - запустите с --force", file=sys.stderr)
            return 1
        print(f"ключ уже есть: {dest}")
    else:
        priv = X25519PrivateKey.generate()
        priv_raw = priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_raw = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(
                {
                    "algorithm": "X25519",
                    "privateKey": _b64(priv_raw),
                    "publicKey": _b64(pub_raw),
                    "created": __import__("datetime").datetime.now().isoformat(
                        timespec="seconds"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        _restrict_acl(dest)
        pub = _b64(pub_raw)
        print(f"создан приватный ключ: {dest}")

    print(f"PUBLIC_KEY={pub}")

    if args.write_module:
        MODULE.parent.mkdir(parents=True, exist_ok=True)
        MODULE.write_text(
            '# -*- coding: utf-8 -*-\n'
            '"""Публичный ключ приёмника диагностики (X25519, base64).\n\n'
            "СГЕНЕРИРОВАНО tools/receiver/gen_keys.py - не редактировать вручную.\n"
            "Приватный ключ лежит только на ПК владельца; этим ключом отчёты\n"
            "только шифруются, расшифровать присланное приложение не может.\n"
            '"""\n'
            "from __future__ import annotations\n\n"
            f'DIAG_PUBLIC_KEY = "{pub}"\n',
            encoding="utf-8",
        )
        print(f"обновлён {MODULE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
