import unittest

from app.analytics.signal_text import fit_trading_signal_reason


class SignalRunnerReasonTests(unittest.TestCase):
    def test_reason_is_trimmed_to_fit_trading_signal_row(self) -> None:
        reason = "x" * 700
        fitted = fit_trading_signal_reason(reason)

        self.assertLessEqual(len(fitted), 500)
        self.assertTrue(fitted.endswith("..."))

    def test_reason_defaults_when_missing(self) -> None:
        self.assertEqual(fit_trading_signal_reason(""), "Signal context unavailable.")
