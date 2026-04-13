import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.analytics.broadcast_desk import (
    _build_posts,
    _group_batch_history,
    _market_bias_snapshot,
    _news_summary,
    _rotate_link,
    validate_status_transition,
)


class BroadcastDeskTests(unittest.TestCase):
    def test_market_bias_snapshot_summarizes_overview(self) -> None:
        snapshot = _market_bias_snapshot(
            {
                "NIFTY": {"trading_signal": {"outlook": "Bullish", "confidence": 76, "state": "setup"}},
                "BANKNIFTY": {"trading_signal": {"outlook": "Bullish", "confidence": 68, "state": "watch"}},
                "SENSEX": {"trading_signal": {"outlook": "Neutral", "confidence": 32, "state": "idle"}},
            }
        )
        self.assertEqual(snapshot["bias"], "Bullish")
        self.assertGreaterEqual(snapshot["probability"], 60)
        self.assertEqual(len(snapshot["symbol_notes"]), 3)

    def test_news_summary_uses_top_critical_alerts(self) -> None:
        summary = _news_summary(
            [
                {"title": "Oil spikes after fresh conflict headlines", "impact_score": 86, "impact_reason": "Oil shock", "affected_symbols": ["NIFTY"]},
                {"title": "Fed official says inflation remains sticky", "impact_score": 78, "impact_reason": "Rates risk", "affected_symbols": ["BANKNIFTY"]},
            ]
        )
        self.assertEqual(summary["impact_score"], 86)
        self.assertEqual(len(summary["headline_lines"]), 2)
        self.assertIn("elevated", summary["expectation"].lower())

    def test_posts_include_rotating_optionthropic_links(self) -> None:
        generated_at = datetime(2026, 3, 26, 6, 0, tzinfo=timezone.utc)
        posts = _build_posts(
            generated_at=generated_at,
            bias_snapshot={
                "bias": "Bullish",
                "probability": 67,
                "symbol_notes": ["NIFTY: Bullish (74%) · setup", "BANKNIFTY: Bullish (69%) · watch"],
            },
            news_summary={
                "impact_score": 81,
                "headline_lines": ["- Oil jumps after conflict headlines (81/100)"],
                "expectation": "News risk is elevated, so conviction should come from both structure and follow-through.",
                "headlines": [
                    {
                        "title": "Oil jumps after conflict headlines",
                        "impact_score": 81,
                        "impact_reason": "Oil shock",
                        "affected_symbols": ["NIFTY", "CRUDEOIL"],
                        "source": "Reuters",
                        "url": "https://example.com",
                    }
                ],
            },
            symbols={
                "NIFTY": {"trading_signal": {"outlook": "Bullish", "support": 23200, "resistance": 23420}},
                "BANKNIFTY": {"trading_signal": {"outlook": "Bullish", "support": 51200, "resistance": 51800}},
                "SENSEX": {"trading_signal": {"outlook": "Neutral", "support": 0, "resistance": 0}},
            },
        )
        self.assertIn("optionthropic.com", posts["morning_bias"]["text"])
        self.assertIn("Optionthropic Intraday Pulse", posts["intraday_update"]["text"])
        self.assertEqual(len(posts["news_alerts"]), 1)

    def test_rotate_link_changes_by_post_key(self) -> None:
        generated_at = datetime(2026, 3, 26, 6, 0, tzinfo=timezone.utc)
        morning = _rotate_link("morning", generated_at)
        closing = _rotate_link("closing", generated_at)
        self.assertNotEqual(morning["url"], closing["url"])

    def test_rotate_link_changes_across_time_buckets(self) -> None:
        early = _rotate_link("morning", datetime(2026, 3, 26, 6, 0, tzinfo=timezone.utc))
        later = _rotate_link("morning", datetime(2026, 3, 26, 9, 30, tzinfo=timezone.utc))
        self.assertNotEqual(early["url"], later["url"])

    def test_group_batch_history_summarizes_statuses(self) -> None:
        rows = [
            SimpleNamespace(
                id="1",
                batch_id="batch-a",
                channel_type="WHATSAPP",
                post_type="MORNING_BIAS",
                title="Morning",
                text="Body",
                bias="Bullish",
                probability=68,
                impact_score=82,
                source=None,
                link_url=None,
                link_label=None,
                context={},
                status="draft",
                generated_at=datetime(2026, 3, 26, 6, 0, tzinfo=timezone.utc),
                created_at=datetime(2026, 3, 26, 6, 0, tzinfo=timezone.utc),
                updated_at=datetime(2026, 3, 26, 6, 0, tzinfo=timezone.utc),
                approved_at=None,
                published_at=None,
            ),
            SimpleNamespace(
                id="2",
                batch_id="batch-a",
                channel_type="WHATSAPP",
                post_type="NEWS_ALERT",
                title="Alert",
                text="Body",
                bias="Bullish",
                probability=68,
                impact_score=82,
                source="Reuters",
                link_url=None,
                link_label=None,
                context={},
                status="published",
                generated_at=datetime(2026, 3, 26, 6, 0, tzinfo=timezone.utc),
                created_at=datetime(2026, 3, 26, 6, 0, tzinfo=timezone.utc),
                updated_at=datetime(2026, 3, 26, 6, 0, tzinfo=timezone.utc),
                approved_at=None,
                published_at=datetime(2026, 3, 26, 6, 5, tzinfo=timezone.utc),
            ),
        ]
        history = _group_batch_history(rows)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status_counts"]["draft"], 1)
        self.assertEqual(history[0]["status_counts"]["published"], 1)

    def test_validate_status_transition_rejects_unknown_value(self) -> None:
        self.assertEqual(validate_status_transition("draft", "approved"), "approved")
        with self.assertRaises(ValueError):
            validate_status_transition("draft", "archived")


if __name__ == "__main__":
    unittest.main()
