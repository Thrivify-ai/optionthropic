import unittest
from datetime import datetime, timezone

from app.alerts.global_news_scoring import NewsCandidate, parse_rss_items, score_news_candidate


class GlobalNewsTests(unittest.TestCase):
    def test_scoring_marks_fed_macro_story_as_critical(self) -> None:
        candidate = NewsCandidate(
            provider="rss",
            source="Reuters",
            title="Federal Reserve signals rate cut path after soft CPI print",
            summary="Bond yields fall as traders price in a faster easing cycle.",
            url="https://example.com/fed-story",
            published_at=datetime(2026, 3, 20, 6, 0, tzinfo=timezone.utc),
        )

        scored = score_news_candidate(candidate, now_utc=datetime(2026, 3, 20, 6, 30, tzinfo=timezone.utc))

        self.assertTrue(scored["is_critical"])
        self.assertGreaterEqual(scored["impact_score"], 70)
        self.assertEqual(scored["severity"], "HIGH")
        self.assertIn("NIFTY", scored["affected_symbols"])
        self.assertIn("BANKNIFTY", scored["affected_symbols"])

    def test_scoring_keeps_energy_shock_more_broad_than_bank_specific(self) -> None:
        candidate = NewsCandidate(
            provider="rss",
            source="CNBC",
            title="Oil jumps after OPEC signals fresh supply cuts",
            summary="Brent rises sharply as the market prices tighter energy supply.",
            url="https://example.com/oil-story",
            published_at=datetime(2026, 3, 20, 5, 0, tzinfo=timezone.utc),
        )

        scored = score_news_candidate(candidate, now_utc=datetime(2026, 3, 20, 6, 0, tzinfo=timezone.utc))

        self.assertTrue(scored["is_critical"])
        self.assertIn("CRUDEOIL", scored["affected_symbols"])
        self.assertIn("NIFTY", scored["affected_symbols"])
        self.assertIn("SENSEX", scored["affected_symbols"])

    def test_scoring_marks_natgas_supply_story_as_critical(self) -> None:
        candidate = NewsCandidate(
            provider="rss",
            source="Reuters",
            title="Natural gas surges after LNG outage and larger-than-expected EIA storage draw",
            summary="Pipeline disruption tightens supply expectations and fuels volatility in gas markets.",
            url="https://example.com/natgas-story",
            published_at=datetime(2026, 3, 20, 5, 30, tzinfo=timezone.utc),
        )

        scored = score_news_candidate(candidate, now_utc=datetime(2026, 3, 20, 6, 0, tzinfo=timezone.utc))

        self.assertTrue(scored["is_critical"])
        self.assertGreaterEqual(scored["impact_score"], 70)
        self.assertIn("NATGAS", scored["affected_symbols"])

    def test_scoring_penalizes_stale_macro_story(self) -> None:
        candidate = NewsCandidate(
            provider="rss",
            source="Reuters",
            title="Federal Reserve signals rate cuts after soft inflation print",
            summary="Bond yields fall as traders reprice the policy path.",
            url="https://example.com/stale-fed-story",
            published_at=datetime(2026, 3, 16, 6, 0, tzinfo=timezone.utc),
        )

        scored = score_news_candidate(candidate, now_utc=datetime(2026, 3, 20, 8, 0, tzinfo=timezone.utc))

        self.assertFalse(scored["is_critical"])
        self.assertLess(scored["impact_score"], 70)

    def test_scoring_filters_low_signal_story(self) -> None:
        candidate = NewsCandidate(
            provider="rss",
            source="Unknown",
            title="Company launches a new consumer product",
            summary="The product is expected to hit stores next quarter.",
            url="https://example.com/product-story",
            published_at=datetime(2026, 3, 20, 6, 0, tzinfo=timezone.utc),
        )

        scored = score_news_candidate(candidate, now_utc=datetime(2026, 3, 20, 8, 0, tzinfo=timezone.utc))

        self.assertFalse(scored["is_critical"])
        self.assertEqual(scored["move_potential"], "IGNORE")

    def test_rss_parser_extracts_basic_fields(self) -> None:
        xml_text = """
        <rss>
          <channel>
            <item>
              <title>Rupee weakens as oil extends rally</title>
              <link>https://example.com/rupee</link>
              <description><![CDATA[USDINR rises after crude prices jump.]]></description>
              <pubDate>Fri, 20 Mar 2026 06:30:00 GMT</pubDate>
              <source>Reuters</source>
            </item>
          </channel>
        </rss>
        """

        rows = parse_rss_items(xml_text)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, "Reuters")
        self.assertIn("USDINR", rows[0].summary)
        self.assertEqual(rows[0].url, "https://example.com/rupee")


if __name__ == "__main__":
    unittest.main()
