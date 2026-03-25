"""
Generate Zerodha access token from a fresh request_token.

- ZERODHA_API_KEY, ZERODHA_API_SECRET: from .env (Docker injects .env via compose)
- request_token: first CLI argument (paste after login)

  docker exec -it optionthropic_backend python /app/generate_token.py <request_token>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    _here = Path(__file__).resolve().parent
    for base in [_here, *_here.parents]:
        _env = base / ".env"
        if _env.is_file():
            load_dotenv(_env)
            break
except ImportError:
    pass

from kiteconnect import KiteConnect


def main() -> int:
    api_key = os.environ.get("ZERODHA_API_KEY", "").strip()
    api_secret = os.environ.get("ZERODHA_API_SECRET", "").strip()
    request_token = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not request_token:
        request_token = os.environ.get("ZERODHA_REQUEST_TOKEN", "").strip()

    if not api_key or not api_secret:
        print("Set ZERODHA_API_KEY and ZERODHA_API_SECRET in .env", file=sys.stderr)
        return 1
    if not request_token:
        print(
            "Usage: python generate_token.py <request_token>\n"
            "Get request_token from the browser URL after Kite login.",
            file=sys.stderr,
        )
        return 1

    try:
        kite = KiteConnect(api_key=api_key)
        data = kite.generate_session(request_token, api_secret=api_secret)
    except Exception as e:  # noqa: BLE001
        print("generate_session failed:", e, file=sys.stderr)
        return 1

    access = data.get("access_token", "")
    print("\nACCESS TOKEN:", access)
    print("\nAdd to .env:\n  ZERODHA_ACCESS_TOKEN=" + access + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
