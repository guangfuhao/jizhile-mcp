from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .credentials import save_credentials

PAGE = """<!doctype html><html lang=zh-CN><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>极致了 API 配置</title><style>body{font:16px system-ui;max-width:540px;margin:64px auto;padding:20px;background:#f6f8fb}input{width:95%;padding:12px;margin:8px 0 20px}button{padding:12px 24px}p{line-height:1.7}</style>
<h1>极致了 API 配置</h1><p>密钥只保存在本机。保存后临时服务会自动退出。</p>
<form method=post><label>API Key<input type=password name=api_key required autocomplete=off></label>
<label>附加码（没有可留空）<input type=password name=verifycode autocomplete=off></label><button>保存</button></form>
<p>默认：单次1元、每日2元、保留1元余额。所有业务查询先报价，实际费用由服务方结算。</p></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def authorized(self):
        token = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("setup", [""])[0]
        origin = self.headers.get("Origin")
        expected = f"http://127.0.0.1:{self.server.server_port}"
        return secrets.compare_digest(token, self.server.setup_token) and (origin is None or origin == expected) and self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def send(self, status, body):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send(200, PAGE) if self.authorized() else self.send(404, "配置链接无效或已过期")

    def do_POST(self):
        if not self.authorized():
            self.send(403, "配置链接无效或来源不匹配")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError()
            fields = urllib.parse.parse_qs(self.rfile.read(length).decode())
            save_credentials(fields.get("api_key", [""])[0], fields.get("verifycode", [""])[0])
        except (OSError, ValueError):
            self.send(400, "无法保存配置，请检查输入")
            return
        self.send(200, "<meta charset=utf-8>配置已保存，临时服务已停止，可以关闭页面。")
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def serve(timeout: int, open_browser: bool, rendezvous: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.setup_token = secrets.token_urlsafe(32)
    url = f"http://127.0.0.1:{server.server_port}/?setup={server.setup_token}"
    fd = os.open(rendezvous, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(url)
    timer = threading.Timer(timeout, server.shutdown)
    timer.daemon = True
    timer.start()
    try:
        if open_browser:
            webbrowser.open(url)
        server.serve_forever(poll_interval=0.1)
    finally:
        timer.cancel()
        server.server_close()
        rendezvous.unlink(missing_ok=True)


def launch_setup_service(open_browser=True, timeout=600):
    rendezvous = Path(tempfile.gettempdir()) / ("jizhile-setup-" + secrets.token_hex(16))
    process = subprocess.Popen([sys.executable, "-m", "jizhile_mcp.setup_server", "--serve", "--rendezvous", str(rendezvous),
                                "--timeout", str(timeout), *([] if open_browser else ["--no-open"])],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               close_fds=True, start_new_session=True)
    for _ in range(100):
        if rendezvous.exists():
            url = rendezvous.read_text(); rendezvous.unlink(missing_ok=True)
            return {"started": True, "pid": process.pid, "url": url, "expires_in_seconds": timeout}
        if process.poll() is not None:
            break
        time.sleep(0.03)
    if process.poll() is None:
        process.terminate(); process.wait(timeout=5)
    rendezvous.unlink(missing_ok=True)
    return {"started": False, "message": "配置服务未启动"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--rendezvous")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    timeout = max(5, min(args.timeout, 600))
    if args.serve:
        serve(timeout, not args.no_open, Path(args.rendezvous))
    else:
        print(json.dumps(launch_setup_service(not args.no_open, timeout), ensure_ascii=False))


if __name__ == "__main__":
    main()
