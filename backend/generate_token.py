# docker cp only uploads this file. To run inside the container:
#   docker exec -it optionthropic_backend python /app/generate_token.py
#
# Prefer `python scripts/zerodha_login.py` from the repo root on your host.
# This helper is intentionally secret-free and expects env vars.
import os

from kiteconnect import KiteConnect


API_KEY = os.environ.get("ZERODHA_API_KEY", "").strip()
API_SECRET = os.environ.get("ZERODHA_API_SECRET", "").strip()
REQUEST_TOKEN = os.environ.get("ZERODHA_REQUEST_TOKEN", "").strip()

if not API_KEY or not API_SECRET or not REQUEST_TOKEN:
    raise SystemExit(
        "Missing ZERODHA_API_KEY, ZERODHA_API_SECRET, or ZERODHA_REQUEST_TOKEN in the environment."
    )

kite = KiteConnect(api_key=API_KEY)
data = kite.generate_session(REQUEST_TOKEN, api_secret=API_SECRET)

print("\nACCESS TOKEN:", data["access_token"])
print("\nCopy the token above and paste it into .env as ZERODHA_ACCESS_TOKEN=\n")

# https://kite.zerodha.com/connect/login?api_key=<your_api_key>&v=3
