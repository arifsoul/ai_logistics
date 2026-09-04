"""Guardrail + chart-shaping checks for the text-to-SQL agent.

Runnable: `python -m unittest tests.test_sql_agent`. Needs Postgres for the
execution tests; no LLM calls.
"""

import unittest

from sqlalchemy.exc import SQLAlchemyError

from backend.sql_agent import (
    MAX_ROWS,
    SqlAgentError,
    build_chart,
    run_sql,
    sanitize_sql,
)


class SanitizeSqlTests(unittest.TestCase):
    def test_adds_limit_and_strips_fence(self):
        sql = sanitize_sql("```sql\nSELECT carrier FROM orders;\n```")
        self.assertEqual(sql, f"SELECT carrier FROM orders LIMIT {MAX_ROWS}")

    def test_keeps_existing_limit(self):
        self.assertEqual(
            sanitize_sql("SELECT carrier FROM orders LIMIT 5"),
            "SELECT carrier FROM orders LIMIT 5",
        )

    def test_allows_leading_cte(self):
        self.assertTrue(
            sanitize_sql("WITH t AS (SELECT 1 AS v) SELECT v FROM t").startswith("WITH")
        )

    def test_rejects_writes_and_stacking(self):
        for bad in (
            "DELETE FROM orders",
            "UPDATE orders SET status = 'delivered'",
            "DROP TABLE orders",
            "SELECT 1; SELECT 2",
            "SELECT pg_sleep(10)",
            "INSERT INTO orders (order_id) VALUES ('x')",
            "",
        ):
            with self.subTest(sql=bad), self.assertRaises(SqlAgentError):
                sanitize_sql(bad)


class BuildChartTests(unittest.TestCase):
    def test_bar_for_categories(self):
        chart = build_chart(["label", "value"], [["UPS", 10], ["DHL", 4]])
        self.assertEqual(chart["type"], "bar")
        self.assertEqual(chart["labels"], ["UPS", "DHL"])
        self.assertEqual(chart["values"], [10, 4])

    def test_line_for_months(self):
        chart = build_chart(["label", "value"], [["2025-01", 3], ["2025-02", 7]])
        self.assertEqual(chart["type"], "line")

    def test_none_when_not_chartable(self):
        self.assertIsNone(build_chart(["value"], [[1], [2]]))  # single column
        self.assertIsNone(build_chart(["label", "value"], [["UPS", 10]]))  # one row


class RunSqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.total = run_sql("SELECT COUNT(*) AS n FROM orders")["rows"][0][0]
        except SQLAlchemyError as error:
            raise unittest.SkipTest(f"Postgres unavailable: {error}") from error
        if not cls.total:
            raise unittest.SkipTest("orders is empty; run `python -m backend.seed`")

    def test_select_returns_columns_and_jsonable_rows(self):
        result = run_sql("SELECT order_id, order_date, order_value_usd FROM orders LIMIT 1")
        self.assertEqual(result["columns"], ["order_id", "order_date", "order_value_usd"])
        order_id, order_date, value = result["rows"][0]
        self.assertIsInstance(order_id, str)
        self.assertRegex(order_date, r"^\d{4}-\d{2}-\d{2}$")  # date -> ISO string
        self.assertIsInstance(value, float)  # Decimal -> float

    def test_transaction_is_read_only(self):
        with self.assertRaises(Exception):
            run_sql("DELETE FROM orders WHERE FALSE")


if __name__ == "__main__":
    unittest.main()
