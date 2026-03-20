#!/usr/bin/env python3
"""
Semi-automatic Zerodha Kite access token refresh.

Zerodha does not allow fully unattended token generation — a human must complete
login (password + 2FA) in the browser. This script:

  1. Starts a tiny web server on 127.0.0.1
  2. Opens the Kite login page
  3. After you log in, Zerodha redirects to your registered redirect URL with
     ?request_token=... — this script captures it
  4. Exchanges request_token for access_token and updates .env

ONE-TIME SETUP (Kite Connect developer console for this app):
  Set the "Redirect URL" to EXACTLY (pick one port, default 8765):

    http://127.0.0.1:8765/

  If you use another port:  python scripts/zerodha_login.py --port 9999
  and register that URL instead.

USAGE (run on your PC, not inside Docker — browser + callback must hit your host):

  cd repo root
  pip install kiteconnect python-dotenv   # if needed
  python scripts/zerodha_login.py

  Then restart backend so it picks up .env:

  docker compose restart backend

ENV (.env in repo root):
  ZERODHA_API_KEY
  ZERODHA_API_SECRET
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def _find_repo_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "docker-compose.yml").is_file() or (p / "backend").is_dir():
            return p
    return start


def _load_dotenv(repo_root: Path) -> None:
    if not load_dotenv:
        return
    env = repo_root / ".env"
    if env.is_file():
        load_dotenv(env)


def _patch_env_value(env_path: Path, key: str, value: str) -> None:
    raw = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = raw.splitlines()
    prefix = f"{key}="
    out: list[str] = []
    found = False
    for line in lines:
        if line.startswith(prefix):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")


def _make_handler_class():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            qs = parse_qs(urlparse(self.path).query)
            token_list = qs.get("request_token") or []
            token = token_list[0] if token_list else None
            status = (qs.get("status") or [""])[0]

            if token:
                self.server.request_token = token  # type: ignore[attr-defined]
                body = b"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Optionthropic</title></head>
<body style="font-family:system-ui;padding:2rem;">
<h1>Login received</h1>
<p>You can close this tab and return to the terminal.</p>
</body></html>"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            # Zerodha may redirect with status=error
            if status == "error" or qs.get("error_type"):
                self.server.login_error = f"status={status!r} qs={qs!r}"  # type: ignore[attr-defined]
                self.send_response(400)
                self.end_headers()
                return

            self.send_response(404)
            self.end_headers()

    return Handler


def main() -> int:
    repo_root = _find_repo_root(Path(__file__).resolve().parent)
    _load_dotenv(repo_root)

    parser = argparse.ArgumentParser(description="Capture Zerodha request_token and refresh .env access token.")
    parser.add_argument("--port", type=int, default=8765, help="Local callback port (default 8765)")
    parser.add_argument(
        "--no-write-env",
        action="store_true",
        help="Only print access token; do not modify .env",
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser; open login URL yourself")
    args = parser.parse_args()

    import os

    api_key = os.environ.get("ZERODHA_API_KEY", "").strip()
    api_secret = os.environ.get("ZERODHA_API_SECRET", "").strip()
    if not api_key or not api_secret:
        print(
            "Missing ZERODHA_API_KEY or ZERODHA_API_SECRET in environment.\n"
            f"Add them to {repo_root / '.env'}",
            file=sys.stderr,
        )
        return 1

    handler = _make_handler_class()
    httpd = HTTPServer(("127.0.0.1", args.port), handler)
    httpd.request_token = None  # type: ignore[attr-defined]
    httpd.login_error = None  # type: ignore[attr-defined]

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    login_url = f"https://kite.zerodha.com/connect/login?api_key={api_key}&v=3"
    callback = f"http://127.0.0.1:{args.port}/"

    print("\n--- Zerodha auto login ---")
    print(f"Listening on {callback}")
    print("Ensure this EXACT URL is set as Redirect URL in your Kite app settings.\n")
    if args.no_browser:
        print(f"Open this URL in your browser:\n  {login_url}\n")
    else:
        print("Opening browser…\n")
        webbrowser.open(login_url)

    deadline = time.time() + 600
    try:
        while time.time() < deadline:
            if getattr(httpd, "login_error", None):
                print(f"Login error from redirect: {httpd.login_error}", file=sys.stderr)
                return 1
            tok = getattr(httpd, "request_token", None)
            if tok:
                break
            time.sleep(0.25)
        else:
            print("Timed out waiting for redirect (10 min). Try again.", file=sys.stderr)
            return 1
    finally:
        httpd.shutdown()
        thread.join(timeout=5)

    from kiteconnect import KiteConnect

    try:
        kite = KiteConnect(api_key=api_key)
        data = kite.generate_session(tok, api_secret=api_secret)
    except Exception as e:  # noqa: BLE001
        print(f"generate_session failed: {e}", file=sys.stderr)
        print("If request_token was already used, run this script again and log in once.", file=sys.stderr)
        return 1

    access = data.get("access_token", "")
    if not access:
        print("No access_token in response", file=sys.stderr)
        return 1

    print(f"\nACCESS TOKEN obtained (length {len(access)}).\n")

    env_path = repo_root / ".env"
    if args.no_write_env:
        print(f"ZERODHA_ACCESS_TOKEN={access}\n")
        print(f"Add to .env manually, then restart backend.\n")
        return 0

    _patch_env_value(env_path, "ZERODHA_ACCESS_TOKEN", access)
    print(f"Updated {env_path} — ZERODHA_ACCESS_TOKEN")
    print("Restart backend:  docker compose restart backend\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
