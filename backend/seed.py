"""One-shot loader: CSV -> Postgres `orders`, plus schema metadata -> pgvector.

    python -m backend.seed              # orders + schema docs
    python -m backend.seed --no-vectors # orders only (skips embedding calls)

The schema context is introspected from the freshly loaded table by
`backend.ddl_docs`, so the column types and the listed distinct values always
match the data that was just inserted.

Idempotent: `orders` is truncated and reloaded, `schema_docs` is replaced.
"""

import argparse
import csv
import getpass
import sys
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import text

from backend.database import Base, SessionLocal, engine
from backend.auth import get_password_hash
from backend.models_db import Order, User
from backend.roles import (
    CANONICAL_SUPERADMIN_USERNAME,
    validate_superadmin_password,
)

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "mock_logistics_data.csv"


def parse_date(value: str) -> date | None:
    value = (value or "").strip()
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def read_csv(path: Path) -> list[dict]:
    """CSV rows coerced to the `orders` column types."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [
            {
                "order_id": row["order_id"],
                "client_id": row["client_id"],
                "order_date": parse_date(row["order_date"]),
                "delivery_date": parse_date(row["delivery_date"]),
                "carrier": row["carrier"],
                "origin_city": row["origin_city"],
                "destination_city": row["destination_city"],
                "status": row["status"],
                "sku": row["sku"],
                "product_category": row["product_category"],
                "quantity": int(row["quantity"] or 0),
                "unit_price_usd": row["unit_price_usd"] or 0,
                "order_value_usd": row["order_value_usd"] or 0,
                "is_promo": row["is_promo"].strip() in ("1", "true", "True"),
                "promo_discount_pct": int(row["promo_discount_pct"] or 0),
                "region": row["region"],
                "warehouse": row["warehouse"],
            }
            for row in csv.DictReader(handle)
        ]


def init_db() -> None:
    """Enable pgvector, then create any missing table."""
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)


def load_orders(rows: list[dict]) -> int:
    db = SessionLocal()
    try:
        db.execute(text("TRUNCATE TABLE orders"))
        db.bulk_insert_mappings(Order, rows)
        db.commit()
        return db.query(Order).count()
    finally:
        db.close()


def load_schema_docs() -> int:
    """Regenerate `schema_sql/orders.sql` from the live table and embed it."""
    # Imported here so `--no-vectors` works without an API key.
    from backend import ddl_docs

    db = SessionLocal()
    try:
        return ddl_docs.sync(db, force=True)["documents"]
    finally:
        db.close()


def seed_superadmin(password: str) -> bool:
    """Create or update the canonical superadmin in PostgreSQL using a hash."""
    password = validate_superadmin_password(password)
    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter(User.username == CANONICAL_SUPERADMIN_USERNAME)
            .first()
        )
        if user is None:
            user = User(username=CANONICAL_SUPERADMIN_USERNAME)
            db.add(user)

        user.hashed_password = get_password_hash(password)
        user.visible_password = None
        user.role = "superadmin"
        db.query(User).filter(
            User.role == "superadmin",
            User.username != CANONICAL_SUPERADMIN_USERNAME,
        ).update({User.role: "admin"}, synchronize_session=False)
        db.commit()
        return True
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-vectors", action="store_true", help="skip embedding schema metadata"
    )
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    parser.add_argument(
        "--superadmin-password",
        help="seed the canonical superadmin password into PostgreSQL",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"CSV not found: {args.csv}")
        return 1

    init_db()
    if args.superadmin_password:
        seed_superadmin(args.superadmin_password)
        print(f"superadmin: {CANONICAL_SUPERADMIN_USERNAME} seeded")
    elif sys.stdin.isatty():
        password = getpass.getpass(
            f"Password for {CANONICAL_SUPERADMIN_USERNAME} (leave blank to skip): "
        )
        if password:
            seed_superadmin(password)
            print(f"superadmin: {CANONICAL_SUPERADMIN_USERNAME} seeded")
    rows = read_csv(args.csv)
    count = load_orders(rows)
    print(f"orders: {count} rows loaded from {args.csv.name}")

    if args.no_vectors:
        print("schema_docs: skipped (--no-vectors)")
    else:
        print(f"schema_docs: {load_schema_docs()} documents embedded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
