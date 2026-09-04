"""Read-only analytics over the `orders` table in Postgres.

Every metric is computed by SQL, so the API always reflects what is in the
database. The public surface (`kpis`, `query`, `forecast`, `ask`) and its
response shapes are unchanged from the CSV version the dashboard already reads.
"""

import re
from datetime import date, datetime
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import text

from backend.database import SessionLocal


class LogisticsAnalytics:
    """SQL-backed analytics over `orders`."""

    # Dimension -> SQL grouping expression.
    DIMENSION_SQL = {
        "week": "to_char(order_date, 'IYYY-\"W\"IW')",
        "month": "to_char(order_date, 'YYYY-MM')",
        "carrier": "carrier",
        "destination_city": "destination_city",
        "origin_city": "origin_city",
        "region": "region",
        "warehouse": "warehouse",
        "sku": "sku",
    }
    # Metric -> SQL aggregate. `delay_rate` divides by delivered+delayed only:
    # in_transit and canceled orders are neither late nor on time yet.
    METRIC_SQL = {
        "orders": "COUNT(*)",
        "delivered_orders": "COUNT(*) FILTER (WHERE status = 'delivered')",
        "delayed_orders": "COUNT(*) FILTER (WHERE status = 'delayed')",
        "delay_rate": (
            "ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'delayed')"
            " / NULLIF(COUNT(*) FILTER (WHERE status IN ('delivered', 'delayed')), 0), 2)"
        ),
    }
    ALLOWED_DIMENSIONS = set(DIMENSION_SQL)
    ALLOWED_METRICS = set(METRIC_SQL)

    def __init__(self, session_factory=SessionLocal):
        self.session_factory = session_factory

    def _fetch(self, sql: str, **params: Any) -> List[Dict[str, Any]]:
        with self.session_factory() as session:
            return [dict(row) for row in session.execute(text(sql), params).mappings()]

    @staticmethod
    def _filters(
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        carrier: Optional[str] = None,
        sku: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """WHERE clause plus its bound parameters. Values are never inlined."""
        clauses = ["TRUE"]
        params: Dict[str, Any] = {}
        if date_from:
            clauses.append("order_date >= :date_from")
            params["date_from"] = date_from
        if date_to:
            clauses.append("order_date <= :date_to")
            params["date_to"] = date_to
        if carrier:
            clauses.append("carrier = :carrier")
            params["carrier"] = carrier
        if sku:
            clauses.append("sku = :sku")
            params["sku"] = sku
        return " AND ".join(clauses), params

    def kpis(self) -> Dict[str, Any]:
        row = self._fetch(
            """
            SELECT COUNT(*) AS total_orders,
                   COUNT(*) FILTER (WHERE status = 'delivered') AS delivered_orders,
                   COUNT(*) FILTER (WHERE status = 'delayed') AS delayed_orders,
                   ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'delivered')
                         / NULLIF(COUNT(*) FILTER (WHERE status IN ('delivered', 'delayed')), 0),
                         2) AS on_time_delivery_rate,
                   ROUND(AVG(delivery_date - order_date)
                         FILTER (WHERE status = 'delivered' AND delivery_date IS NOT NULL),
                         2) AS average_delivery_days
            FROM orders
            """
        )[0]
        return {
            "total_orders": int(row["total_orders"]),
            "delivered_orders": int(row["delivered_orders"]),
            "delayed_orders": int(row["delayed_orders"]),
            "on_time_delivery_rate": float(row["on_time_delivery_rate"] or 0),
            "average_delivery_days": float(row["average_delivery_days"] or 0),
        }

    def query(
        self,
        metric: str,
        dimension: str,
        date_range: str = "all",
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        carrier: Optional[str] = None,
        sku: Optional[str] = None,
    ) -> Dict[str, Any]:
        if metric not in self.ALLOWED_METRICS:
            raise ValueError(f"Unsupported metric: {metric}")
        if dimension not in self.ALLOWED_DIMENSIONS:
            raise ValueError(f"Unsupported dimension: {dimension}")

        where, params = self._filters(date_from, date_to, carrier, sku)
        sql = (
            f"SELECT {self.DIMENSION_SQL[dimension]} AS label,"
            f" {self.METRIC_SQL[metric]} AS value,"
            " COUNT(*) AS matched"
            f" FROM orders WHERE {where}"
            " GROUP BY label ORDER BY label"
        )
        records = self._fetch(sql, **params)

        cast = float if metric == "delay_rate" else int
        result_rows = [
            {"label": record["label"], "value": cast(record["value"] or 0)}
            for record in records
        ]

        return {
            "answer": self._answer(metric, dimension, result_rows),
            "chart": {
                "type": "line" if dimension in {"week", "month"} else "bar",
                "labels": [row["label"] for row in result_rows],
                "values": [row["value"] for row in result_rows],
            },
            "interpretation": {
                "metric": metric,
                "dimensions": [dimension],
                "filters": {
                    "date_range": date_range,
                    "date_from": date_from.isoformat() if date_from else None,
                    "date_to": date_to.isoformat() if date_to else None,
                    "carrier": carrier,
                    "sku": sku,
                },
                "query_plan": sql,
                "row_count": sum(int(record["matched"]) for record in records),
            },
            "rows": result_rows,
        }

    def forecast(self, sku: str, horizon_months: int) -> Dict[str, Any]:
        if horizon_months < 1 or horizon_months > 12:
            raise ValueError("horizon_months must be between 1 and 12")

        historical = [
            {"period": record["period"], "value": int(record["value"] or 0)}
            for record in self._fetch(
                """
                SELECT to_char(order_date, 'YYYY-MM') AS period,
                       SUM(quantity) AS value
                FROM orders WHERE sku = :sku
                GROUP BY period ORDER BY period
                """,
                sku=sku,
            )
        ]
        if not historical:
            raise ValueError(f"SKU not found: {sku}")

        baseline = round(mean([row["value"] for row in historical[-3:]]), 2)
        last_period = datetime.strptime(historical[-1]["period"], "%Y-%m").date()
        forecast = []
        for offset in range(1, horizon_months + 1):
            month = (last_period.month - 1 + offset) % 12 + 1
            year = last_period.year + (last_period.month - 1 + offset) // 12
            forecast.append({"period": f"{year:04d}-{month:02d}", "value": baseline})

        return {
            "sku": sku,
            "method": "moving_average",
            "historical": historical,
            "forecast": forecast,
            "inventory_recommendation": round(baseline * 1.15, 2),
            "explanation": "Forecast uses the mean quantity of the latest three observed months with a 15% safety buffer.",
        }

    def ask(self, question: str) -> Dict[str, Any]:
        """Route a supported natural-language question to a computed tool."""
        normalized = question.lower().strip()
        sku_match = re.search(r"\b([a-z]+-\d{4})\b", normalized)
        if any(
            term in normalized
            for term in (
                "predict",
                "forecast",
                "projection",
                "inventory",
                "prediksi",
                "proyeksi",
                "ramalan",
                "perkiraan",
                "restock",
                "reorder",
                "stok",
            )
        ):
            if not sku_match:
                raise ValueError("Forecast questions must include a SKU, for example PAPER-0197")
            horizon_match = re.search(r"(\d+)\s*(?:months?|bulan)", normalized)
            horizon = int(horizon_match.group(1)) if horizon_match else 4
            return {"tool": "forecast", "interpretation": {"sku": sku_match.group(1).upper(), "horizon_months": horizon}, **self.forecast(sku_match.group(1).upper(), horizon)}

        date_range = "all"
        date_from = None
        date_to = None
        known_dates = self._fetch("SELECT MAX(order_date) AS latest FROM orders")[0][
            "latest"
        ]
        if "last 3 months" in normalized and known_dates:
            date_to = known_dates
            date_from = self._shift_months(date_to.replace(day=1), -2)
            date_range = "last_3_months"
        elif "last month" in normalized and known_dates:
            date_to = known_dates
            date_from = self._shift_months(date_to.replace(day=1), -1)
            date_to = self._shift_months(date_to.replace(day=1), 0)
            date_range = "last_month"

        if "carrier" in normalized and "delay rate" in normalized:
            result = self.query("delay_rate", "carrier", date_range, date_from, date_to)
        elif "delayed" in normalized or "late" in normalized:
            dimension = "week" if "week" in normalized else "month"
            result = self.query("delayed_orders", dimension, date_range, date_from, date_to)
        elif "order" in normalized:
            result = self.query("orders", "month", date_range, date_from, date_to)
        else:
            raise ValueError("Unsupported question. Try a carrier delay, delayed orders, or SKU forecast question.")
        return {"tool": "analytics", **result}

    @staticmethod
    def _shift_months(value: date, months: int) -> date:
        month_index = value.year * 12 + value.month - 1 + months
        year, month = divmod(month_index, 12)
        return date(year, month + 1, 1)

    @staticmethod
    def _answer(metric: str, dimension: str, rows: Iterable[Dict[str, Any]]) -> str:
        rows = list(rows)
        if not rows:
            return "No matching logistics records were found."
        best = max(rows, key=lambda row: row["value"])
        labels = {"delay_rate": "delay rate", "delayed_orders": "delayed orders"}
        metric_name = labels.get(metric, metric.replace("_", " "))
        return f"{best['label']} has the highest {metric_name}: {best['value']}%." if metric == "delay_rate" else f"{best['label']} has the highest {metric_name}: {best['value']}."