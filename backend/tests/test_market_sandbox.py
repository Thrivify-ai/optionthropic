import unittest

from app.analytics.market_sandbox import list_sandbox_scenarios, run_market_sandbox


class MarketSandboxTests(unittest.TestCase):
    def test_lists_supported_scenarios(self) -> None:
        scenarios = list_sandbox_scenarios()
        names = {row["name"] for row in scenarios}
        self.assertIn("trend_up_news", names)
        self.assertIn("range_whipsaw", names)

    def test_trend_sandbox_produces_frames_and_summary(self) -> None:
        payload = run_market_sandbox(
            symbol="NIFTY",
            scenario_name="trend_up_news",
            steps=120,
            seed=7,
        )

        self.assertEqual(payload["symbol"], "NIFTY")
        self.assertEqual(payload["scenario"], "trend_up_news")
        self.assertEqual(len(payload["frames"]), 120)
        self.assertIn("quick", payload["summary"])
        self.assertIn("long", payload["summary"])
        self.assertTrue(any(frame["quick"]["signal"] in {"Buy CE", "Wait"} for frame in payload["frames"]))
        self.assertTrue(any(frame["long"]["outlook"] != "Neutral" for frame in payload["frames"][60:]))

    def test_range_sandbox_keeps_most_steps_non_directional(self) -> None:
        payload = run_market_sandbox(
            symbol="BANKNIFTY",
            scenario_name="range_whipsaw",
            steps=90,
            seed=11,
        )

        active_quick = sum(1 for frame in payload["frames"] if frame["quick"]["signal"] in {"Buy CE", "Buy PE"})
        self.assertLess(active_quick, len(payload["frames"]) // 3)


if __name__ == "__main__":
    unittest.main()
