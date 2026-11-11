# -*- coding: utf-8 -*-
"""Приёмник обезличенных отчётов диагностики (ПК владельца сборки).

Модель безопасности:
  - слушает только localhost; наружу выставляет Tailscale Funnel (или
    обратный прокси), поэтому порт не открыт в интернет напрямую;
  - принимает ТОЛЬКО POST /report с телом до 256 КиБ;
  - расшифровывает приватным ключом владельца (X25519 + HKDF + AES-GCM);
  - ничего из присланного не исполняет и не отдаёт обратно: GET к отчётам
    невозможен, каталог не листается, API чтения отсутствует;
  - жёсткие лимиты размера и частоты (по IP и общий в сутки), чтобы нельзя
    было забить диск или устроить перебор;
  - пишет .json и .txt в каталог отчётов, имя строит из проверенного ID.

Запуск:
    .\\venv\\Scripts\\python.exe tools\\receiver\\diag_receiver.py
    (ключ: %LOCALAPPDATA%\\VPN-LAUNCHER-RECEIVER\\receiver_key.json)

Проверка здоровья (локально):
    curl http://127.0.0.1:8787/health
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# запуск как tools/receiver/diag_receiver.py: пакет vpn_launcher лежит в
# корне проекта, а не рядом со скриптом
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

MAX_BODY = 256 * 1024
MAX_REPORTS_PER_IP_PER_HOUR = 20
MAX_REPORTS_PER_IP_PER_DAY = 60
MAX_REPORTS_PER_DAY = 3000
MAX_CONCURRENT = 8
READ_TIMEOUT = 20

_CREATE_NO_WINDOW = 0x08000000
_ID_RE = re.compile(r"^[0-9a-f]{6,32}$")

DEFAULT_KEY = (
    Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    / "VPN-LAUNCHER-RECEIVER"
    / "receiver_key.json"
)
DEFAULT_REPORTS = DEFAULT_KEY.parent / "reports"


class RateLimiter:
    """Простое скользящее окно + суточные счётчики."""

    def __init__(self) -> None:
        self._hour: dict[str, deque[float]] = defaultdict(deque)
        self._day: dict[str, int] = defaultdict(int)
        self._day_total = 0
        self._day_key = self._today()
        self._lock = threading.Lock()

    @staticmethod
    def _today() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _roll(self) -> None:
        today = self._today()
        if today != self._day_key:
            self._day_key = today
            self._day.clear()
            self._day_total = 0

    def allow(self, ip: str) -> tuple[bool, str]:
        with self._lock:
            self._roll()
            now = time.monotonic()
            q = self._hour[ip]
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= MAX_REPORTS_PER_IP_PER_HOUR:
                return False, "too many reports from this address (hour)"
            if self._day[ip] >= MAX_REPORTS_PER_IP_PER_DAY:
                return False, "too many reports from this address (day)"
            if self._day_total >= MAX_REPORTS_PER_DAY:
                return False, "daily limit reached"
            q.append(now)
            self._day[ip] += 1
            self._day_total += 1
            return True, ""


class Receiver:
    def __init__(self, key_path: Path, reports_dir: Path) -> None:
        data = json.loads(key_path.read_text(encoding="utf-8"))
        self.private_key = str(data.get("privateKey") or "")
        self.public_key = str(data.get("publicKey") or "")
        if not self.private_key:
            raise ValueError("в файле ключа нет privateKey")
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.limiter = RateLimiter()
        self.slots = threading.BoundedSemaphore(MAX_CONCURRENT)

    # -- журнал приёмника: без содержимого отчётов ----------------------
    def log(self, msg: str) -> None:
        path = self.reports_dir.parent / "receiver.log"
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
        try:
            if path.exists() and path.stat().st_size > 1_000_000:
                path.unlink()
            with path.open("a", encoding="utf-8", newline="") as fh:
                fh.write(line + "\r\n")
        except OSError:
            pass

    def store(self, body: bytes) -> tuple[bool, str]:
        from vpn_launcher.core.diagnostics import decrypt_report

        try:
            raw = decrypt_report(body, self.private_key)
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            return False, "cannot decrypt"

        report = payload.get("report") if isinstance(payload, dict) else None
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(report, dict) or not isinstance(text, str):
            return False, "bad payload"
        report_id = str(report.get("id") or "")
        if not _ID_RE.match(report_id):
            return False, "bad id"
        if len(text) > MAX_BODY:
            return False, "text too large"

        day = datetime.now().strftime("%Y-%m-%d")
        out_dir = self.reports_dir / day
        out_dir.mkdir(parents=True, exist_ok=True)
        base = f"report-{datetime.now():%Y%m%d-%H%M%S}-{report_id}"
        js = out_dir / f"{base}.json"
        txt = out_dir / f"{base}.txt"
        tmp = out_dir / f".{base}.tmp"
        try:
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            os.replace(tmp, js)
            txt.write_text(text, encoding="utf-8", newline="\r\n")
        except OSError as exc:
            try:
                tmp.unlink()
            except OSError:
                pass
            self.log(f"write error: {type(exc).__name__}")
            return False, "cannot store"

        verdict = ""
        try:
            verdict = str((report.get("verdict") or {}).get("code") or "")
        except Exception:
            verdict = ""
        self.log(f"accepted id={report_id} bytes={len(raw)} verdict={verdict} file={js.name}")
        return True, report_id


class Handler(BaseHTTPRequestHandler):
    server_version = "VLDiag/1.0"
    sys_version = ""
    timeout = READ_TIMEOUT

    # receiver кладёт в self.server.receiver
    @property
    def receiver(self) -> Receiver:
        return self.server.receiver  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - stdlib API
        # В консоль не пишем содержимое/заголовки: только метод, путь, код.
        try:
            self.receiver.log(f"{self.command} {self.path.split('?')[0]} -> {args[1]}")
        except Exception:
            pass

    def _reply(self, code: int, body: bytes = b"") -> None:
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        if self.path.split("?")[0] == "/health":
            self._reply(200, b'{"ok":true}')
        else:
            self._reply(404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        if self.path.split("?")[0] != "/report":
            self._reply(404)
            return

        ip = str(self.client_address[0] if self.client_address else "?")
        ok, why = self.receiver.limiter.allow(ip)
        if not ok:
            self._reply(429)
            return

        if not self.receiver.slots.acquire(blocking=False):
            self._reply(429)
            return
        try:
            length_hdr = self.headers.get("Content-Length") or ""
            if not length_hdr.isdigit():
                self._reply(411)
                return
            length = int(length_hdr)
            if length <= 0 or length > MAX_BODY:
                self._reply(413)
                return
            body = self.rfile.read(length)
            if len(body) != length:
                self._reply(400)
                return
            stored, detail = self.receiver.store(body)
            if not stored:
                self.receiver.log(f"rejected ip={ip} reason={detail}")
                self._reply(400)
                return
            self.receiver.log(f"ok ip={ip} id={detail}")
            self._reply(204)
        finally:
            self.receiver.slots.release()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="приёмник отчётов VPN LAUNCHER")
    ap.add_argument("--key", default=str(DEFAULT_KEY))
    ap.add_argument("--reports", default=str(DEFAULT_REPORTS))
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args(argv)

    key_path = Path(args.key)
    if not key_path.is_file():
        print(f"нет файла ключа: {key_path}", file=sys.stderr)
        print("сгенерируйте: python tools/receiver/gen_keys.py", file=sys.stderr)
        return 1

    receiver = Receiver(key_path, Path(args.reports))
    httpd = ThreadingHTTPServer((args.bind, args.port), Handler)
    httpd.daemon_threads = True
    httpd.receiver = receiver  # type: ignore[attr-defined]

    print(f"приёмник слушает http://{args.bind}:{args.port}/report")
    print(f"отчёты: {receiver.reports_dir}")
    print(f"публичный ключ: {receiver.public_key}")
    print("остановка: Ctrl+C")
    receiver.log(f"receiver started on {args.bind}:{args.port}")
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        receiver.log("receiver stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
