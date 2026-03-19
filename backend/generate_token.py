from kiteconnect import KiteConnect

API_KEY       = "tx815b2mx4epdv27"
API_SECRET    = "hktqtps8uyh69u60tn63h3xy4x6l3jfw"
REQUEST_TOKEN = "4F2psAwj67MO69nkPeDVtWSWS1kWhyGf"

kite = KiteConnect(api_key=API_KEY)
data = kite.generate_session(REQUEST_TOKEN, api_secret=API_SECRET)

print("\nACCESS TOKEN:", data["access_token"])
print("\nCopy the token above and paste it into .env as ZERODHA_ACCESS_TOKEN=\n")

#https://kite.zerodha.com/connect/login?api_key=tx815b2mx4epdv27&v=3
