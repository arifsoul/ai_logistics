"""Analytics contract over Postgres. Run `python -m backend.seed` first."""

import unittest

from sqlalchemy.exc import SQLAlchemyError

from backend.analytics import LogisticsAnalytics


class LogisticsAnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analytics = LogisticsAnalytics()
        try:
            count = cls.analytics.kpis()["total_orders"]
        except SQLAlchemyError as error:
            # Unreachable database is an environment problem, not a regression.
            raise unittest.SkipTest(f"Postgres unavailable: {error}") from error
        if count == 0:
            raise unittest.SkipTest("orders is empty; run `python -m backend.seed`")

    def test_kpis_use_explicit_delivery_denominator(self):
        kpis = self.analytics.kpis()

        self.assertEqual(kpis["total_orders"], 400)
        self.assertEqual(kpis["delivered_orders"], 304)
        self.assertEqual(kpis["delayed_orders"], 55)
        self.assertAlmostEqual(kpis["on_time_delivery_rate"], 84.68, places=2)
        self.assertAlmostEqual(kpis["average_delivery_days"], 3.25, places=2)

    def test_carrier_query_returns_computed_rows_and_explanation(self):
        result = self.analytics.query(
            metric="delay_rate", dimension="carrier", date_range="all"
        )

        self.assertEqual(result["chart"]["type"], "bar")
        self.assertIn("carrier", result["interpretation"]["dimensions"])
        self.assertIn("filters", result["interpretation"])
        self.assertEqual(len(result["rows"]), 9)

    def test_forecast_returns_historical_and_future_values(self):
        result = self.analytics.forecast("PAPER-0197", 4)

        self.assertEqual(result["method"], "moving_average")
        self.assertEqual(len(result["forecast"]), 4)
        self.assertGreater(len(result["historical"]), 0)
        self.assertIn("inventory_recommendation", result)

    def test_natural_language_query_routes_to_computed_tool(self):
        result = self.analytics.ask("Which carrier has the highest delay rate?")

        self.assertEqual(result["tool"], "analytics")
        self.assertEqual(result["interpretation"]["metric"], "delay_rate")
        self.assertEqual(result["interpretation"]["dimensions"], ["carrier"])

    def test_indonesian_forecast_question_routes_to_forecast(self):
        result = self.analytics.ask("Prediksi stok PAPER-0197 untuk 4 bulan")

        self.assertEqual(result["tool"], "forecast")
        self.assertEqual(result["interpretation"], {
            "sku": "PAPER-0197",
            "horizon_months": 4,
        })
        self.assertEqual(len(result["forecast"]), 4)


if __name__ == "__main__":
    unittest.main()