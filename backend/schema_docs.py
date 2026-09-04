"""Human-written descriptions of the `orders` table, embedded into pgvector.

These strings are the only schema knowledge the text-to-SQL planner has, so
enum values and units belong here — the planner cannot see the data itself.
Keep them in sync with `backend/models_db.py` and re-run the seeder after any
change: `python -m backend.seed`.
"""

TABLE_NAME = "orders"

# Column -> description. Enum values are spelled out so the planner filters on
# real literals instead of inventing them.
COLUMNS: dict[str, str] = {
    "order_id": "TEXT primary key. Unique id of one order, e.g. 'ORD-100001'. Count it for order volume.",
    "client_id": "TEXT. Customer id, e.g. 'CUST-1007'. 30 distinct clients.",
    "order_date": "DATE, never null. When the order was placed. Range 2025-01-01..2025-12-30. Use date_trunc('month', order_date) for monthly trends and to_char(order_date, 'IYYY-\"W\"IW') for ISO weeks.",
    "delivery_date": "DATE, nullable. When the order was delivered. NULL when it has not been delivered (in_transit, canceled, some exception rows). Delivery duration in days = delivery_date - order_date.",
    "carrier": "TEXT. Shipping company. 9 distinct values: 'BluePost', 'CargoLux', 'DHL', 'FedEx', 'GLS', 'NordExpress', 'PostNL', 'UPS', 'USPS'.",
    "origin_city": "TEXT. Ship-from city formatted 'City, ST', e.g. 'Chicago, IL'.",
    "destination_city": "TEXT. Ship-to city formatted 'City, ST', e.g. 'Boston, MA'.",
    "status": "TEXT. Order state, exactly one of 'delivered', 'delayed', 'in_transit', 'exception', 'canceled'. 'delayed' means late; 'exception' means a delivery problem. On-time rate = delivered / (delivered + delayed).",
    "sku": "TEXT. Product code formatted '<CATEGORY>-<4 digits>', e.g. 'PAPER-0197'. 355 distinct SKUs.",
    "product_category": "TEXT. Product family, one of 'BOOK', 'BRUSH', 'CRAYON', 'MARKER', 'PAINT', 'PAPER', 'PENCIL', 'STICKER'.",
    "quantity": "INTEGER. Units ordered in this order.",
    "unit_price_usd": "NUMERIC. Price per unit in USD.",
    "order_value_usd": "NUMERIC. Total order value in USD after discount. Sum it for revenue.",
    "is_promo": "BOOLEAN. True when the order used a promotion.",
    "promo_discount_pct": "INTEGER. Discount percent applied, 0 when is_promo is false.",
    "region": "TEXT. Sales region, one of 'EU', 'UK', 'US-C', 'US-E', 'US-W'.",
    "warehouse": "TEXT. Fulfilment centre code, 9 distinct: 'AMS-FC1', 'ATL-DC1', 'BER-FC1', 'CHI-DC1', 'DFW-DC1', 'EWR-DC1', 'LAX-DC1', 'LON-FC1', 'SFO-DC2'.",
}

OVERVIEW = (
    "Table `orders` is the single source of truth for logistics analytics: one row "
    "per customer order, 400 rows total, no other table exists and there are no "
    "joins. Columns: " + ", ".join(COLUMNS) + "."
)

# Question -> SQL exemplars. These pin down the house rules (on-time denominator,
# delivery-days definition, label/value output shape) far more reliably than prose.
EXAMPLES: dict[str, str] = {
    "on-time delivery rate": (
        "Q: What is the on-time delivery rate?\n"
        "SQL: SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'delivered')\n"
        "     / NULLIF(COUNT(*) FILTER (WHERE status IN ('delivered', 'delayed')), 0), 2)\n"
        "     AS on_time_delivery_rate FROM orders;"
    ),
    "delay rate by carrier": (
        "Q: Which carrier has the highest delay rate?\n"
        "SQL: SELECT carrier AS label,\n"
        "     ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'delayed')\n"
        "     / NULLIF(COUNT(*), 0), 2) AS value\n"
        "     FROM orders GROUP BY carrier ORDER BY value DESC;"
    ),
    "average delivery days": (
        "Q: How long does delivery take on average?\n"
        "SQL: SELECT ROUND(AVG(delivery_date - order_date), 2) AS average_delivery_days\n"
        "     FROM orders WHERE delivery_date IS NOT NULL;"
    ),
    "monthly order volume": (
        "Q: Show order volume per month.\n"
        "SQL: SELECT to_char(date_trunc('month', order_date), 'YYYY-MM') AS label,\n"
        "     COUNT(*) AS value\n"
        "     FROM orders GROUP BY 1 ORDER BY 1;"
    ),
    "revenue by region": (
        "Q: Revenue per region last quarter?\n"
        "SQL: SELECT region AS label, SUM(order_value_usd) AS value\n"
        "     FROM orders\n"
        "     WHERE order_date >= DATE '2025-10-01' AND order_date < DATE '2026-01-01'\n"
        "     GROUP BY region ORDER BY value DESC;"
    ),
    "top skus": (
        "Q: Top 10 SKUs by units sold.\n"
        "SQL: SELECT sku AS label, SUM(quantity) AS value\n"
        "     FROM orders GROUP BY sku ORDER BY value DESC LIMIT 10;"
    ),
}


def build_docs() -> dict[str, str]:
    """`ref -> text` for every document that goes into pgvector."""
    docs = {TABLE_NAME: OVERVIEW}
    docs.update(
        {f"{TABLE_NAME}.{column}": f"orders.{column} — {text}" for column, text in COLUMNS.items()}
    )
    docs.update({f"example:{name}": text for name, text in EXAMPLES.items()})
    return docs


# Compact schema always shown to the planner, regardless of retrieval.
DDL = "orders(" + ", ".join(COLUMNS) + ")"
