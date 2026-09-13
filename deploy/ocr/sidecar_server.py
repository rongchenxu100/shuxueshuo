#!/usr/bin/env python3
"""Persistent OCR HTTP sidecar for product server compose.

Runs inside shuxueshuo-ocr with the repo mounted at /opt/shuxueshuo.
Keeps Paddle models warm; serializes observe requests with a process lock.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import traceback
from io import StringIO

HOST = os.environ.get("PRODUCT_OCR_BIND", "0.0.0.0")
PORT = int(os.environ.get("PRODUCT_OCR_PORT", "8080"))
READY = False
READY_ERROR = ""
LOCK = threading.Lock()


def warmup() -> None:
    from shuxueshuo_server.product import observation as obs

    worker = obs.get_paddle_worker()
    worker.manifests()
    for component in ("layout", "text_ocr", "formula_ocr"):
        worker._model(component)  # noqa: SLF001 — intentional process-level preload


def run_observe(work_dir: str, source_id: str, phase: str) -> dict:
    from shuxueshuo_server.product.observation import ObservationJournal, run

    directory = Path(work_dir)
    if not directory.is_dir():
        return {
            "ok": False,
            "exit_code": 2,
            "stdout": "",
            "stderr": f"work_dir is not a directory: {work_dir}",
        }
    if phase not in ("source", "observation"):
        return {
            "ok": False,
            "exit_code": 2,
            "stdout": "",
            "stderr": f"invalid phase: {phase}",
        }
    stdout, stderr = StringIO(), StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = stdout, stderr
        journal = ObservationJournal(directory, source_id, phase)
        run(journal, directory.name, phase)
        return {"ok": True, "exit_code": 0, "stdout": stdout.getvalue(), "stderr": stderr.getvalue()}
    except Exception:
        stderr.write(traceback.format_exc())
        return {"ok": False, "exit_code": 1, "stdout": stdout.getvalue(), "stderr": stderr.getvalue()}
    finally:
        sys.stdout, sys.stderr = old_out, old_err


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/health":
            if not READY:
                self._send(503, {"ok": False, "ready": False, "error": READY_ERROR or "warming_up"})
                return
            self._send(200, {"ok": True, "ready": True})
            return
        if path == "/v1/manifests":
            if not READY:
                self._send(503, {"ok": False, "ready": False, "error": READY_ERROR or "warming_up"})
                return
            from shuxueshuo_server.product.observation import get_paddle_worker

            payloads = [item.to_payload() for item in get_paddle_worker().manifests()]
            self._send(200, {"ok": True, "providers": payloads})
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/v1/observe":
            self._send(404, {"ok": False, "error": "not_found"})
            return
        if not READY:
            self._send(503, {"ok": False, "ready": False, "error": READY_ERROR or "warming_up"})
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
            work_dir = str(body["work_dir"])
            source_id = str(body["source_id"])
            phase = str(body["phase"])
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            self._send(400, {"ok": False, "exit_code": 2, "stdout": "", "stderr": f"bad request: {exc}"})
            return
        with LOCK:
            result = run_observe(work_dir, source_id, phase)
        self._send(200 if result["exit_code"] == 0 else 500, result)


def main() -> int:
    global READY, READY_ERROR
    try:
        warmup()
        READY = True
    except Exception as exc:
        READY_ERROR = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        # Fail closed: compose healthcheck should restart until models load.
        print(f"ocr sidecar warmup failed: {READY_ERROR}", flush=True)
        return 1
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"ocr sidecar listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
