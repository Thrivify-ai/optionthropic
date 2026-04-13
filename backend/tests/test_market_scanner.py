import unittest

from app.analytics.market_scanner import summarize_market_breadth


class MarketScannerTests(unittest.TestCase):
    def test_summarize_market_breadth_detects_bullish_leadership(self) -> None:
        quotes = {
            "NSE:RELIANCE": {"last_price": 1510, "ohlc": {"close": 1490}},
            "NSE:HDFCBANK": {"last_price": 1710, "ohlc": {"close": 1680}},
            "NSE:ICICIBANK": {"last_price": 1290, "ohlc": {"close": 1265}},
            "NSE:INFY": {"last_price": 1820, "ohlc": {"close": 1800}},
            "NSE:TCS": {"last_price": 4020, "ohlc": {"close": 3985}},
            "NSE:BHARTIARTL": {"last_price": 1440, "ohlc": {"close": 1435}},
            "NSE:ITC": {"last_price": 476, "ohlc": {"close": 470}},
            "NSE:LT": {"last_price": 3810, "ohlc": {"close": 3790}},
            "NSE:SBIN": {"last_price": 820, "ohlc": {"close": 808}},
            "NSE:AXISBANK": {"last_price": 1130, "ohlc": {"close": 1120}},
            "NSE:KOTAKBANK": {"last_price": 1872, "ohlc": {"close": 1865}},
            "NSE:HINDUNILVR": {"last_price": 2520, "ohlc": {"close": 2508}},
        }

        snapshot = summarize_market_breadth("NIFTY", quotes)

        self.assertTrue(snapshot.available)
        self.assertEqual(snapshot.direction_bias, "bullish")
        self.assertGreater(snapshot.breadth_score, 18)
        self.assertTrue(snapshot.aligned_bullish)

    def test_summarize_market_breadth_detects_bearish_leadership(self) -> None:
        quotes = {
            "NSE:HDFCBANK": {"last_price": 1650, "ohlc": {"close": 1690}},
            "NSE:ICICIBANK": {"last_price": 1232, "ohlc": {"close": 1268}},
            "NSE:SBIN": {"last_price": 780, "ohlc": {"close": 807}},
            "NSE:AXISBANK": {"last_price": 1075, "ohlc": {"close": 1112}},
            "NSE:KOTAKBANK": {"last_price": 1798, "ohlc": {"close": 1840}},
            "NSE:INDUSINDBK": {"last_price": 1388, "ohlc": {"close": 1440}},
            "NSE:BANKBARODA": {"last_price": 252, "ohlc": {"close": 261}},
            "NSE:PNB": {"last_price": 118, "ohlc": {"close": 121}},
            "NSE:AUBANK": {"last_price": 682, "ohlc": {"close": 700}},
            "NSE:IDFCFIRSTB": {"last_price": 74, "ohlc": {"close": 76}},
            "NSE:FEDERALBNK": {"last_price": 184, "ohlc": {"close": 190}},
            "NSE:CANBK": {"last_price": 104, "ohlc": {"close": 108}},
        }

        snapshot = summarize_market_breadth("BANKNIFTY", quotes)

        self.assertTrue(snapshot.available)
        self.assertEqual(snapshot.direction_bias, "bearish")
        self.assertLess(snapshot.breadth_score, -18)
        self.assertTrue(snapshot.aligned_bearish)


if __name__ == "__main__":
    unittest.main()
