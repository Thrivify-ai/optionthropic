import requests

url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"

headers = {
 "User-Agent": "Mozilla/5.0",
 "Accept-Language": "en-US,en;q=0.9",
 "Accept-Encoding": "gzip, deflate, br"
}

session = requests.Session()
session.get("https://www.nseindia.com", headers=headers)

response = session.get(url, headers=headers)

data = response.json()
