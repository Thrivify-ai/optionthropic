import unittest

from app.analytics.quick_signal_utils import has_directional_persistence, is_quick_rangebound


class QuickSignalUtilsTests(unittest.TestCase):
    def test_directional_persistence_requires_same_sign_previous_leg(self) -> None:
        self.assertTrue(has_directional_persistence(10.0, 5.0, "bullish"))
        self.assertFalse(has_directional_persistence(10.0, -5.0, "bullish"))
        self.assertTrue(has_directional_persistence(-10.0, -4.0, "bearish"))
        self.assertFalse(has_directional_persistence(-10.0, 4.0, "bearish"))

    def test_quick_rangebound_detects_weak_internal_move(self) -> None:
        self.assertTrue(
            is_quick_rangebound(
                spot=100.0,
                support=98.0,
                resistance=102.0,
                momentum_1m=4.0,
                momentum_3m=6.0,
                bull_threshold=18.0,
                mom_3m_threshold=12.0,
            )
        )
        self.assertFalse(
            is_quick_rangebound(
                spot=103.0,
                support=98.0,
                resistance=102.0,
                momentum_1m=12.0,
                momentum_3m=18.0,
                bull_threshold=18.0,
                mom_3m_threshold=12.0,
            )
        )


if __name__ == "__main__":
    unittest.main()
