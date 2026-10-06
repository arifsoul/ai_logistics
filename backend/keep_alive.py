"""Local Supabase keep-alive heartbeat.

Pings the Supabase REST API so the Free Tier project registers database
activity and is not paused for inactivity. The GitHub Actions workflow in
.github/workflows/keep_alive.yml runs the same request on a schedule; this
script is for manual / local verification.

Usage:
    python -m backend.keep_alive
    python -m backend.keep_alive --table orders

Reads the project URL and anon key from the environment, falling back to the
values the frontend already uses:

    NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY

Set SUPABASE_URL / SUPABASE_ANON_KEY to override (these are the names the
GitHub Actions workflow uses as repository secrets).
"""

from __future__ import annotations

import argparse
import os
import sys
from urllib import error, request

DEFAULT_TABLE = "orders"
TIMEOUT_SECONDS = 30


def _load_env_file() -> None:
    """Populate os.environ from frontend/.env.local when values are missing."""
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_ANON_KEY"):
        return

    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "frontend",
        ".env.local",
    )
    if not os.path.exists(env_path):
        return

    with open(env_path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(name, value)


def resolve_credentials() -> tuple[str, str]:
    _load_env_file()

    url = os.environ.get("SUPABASE_URL") or os.environ.get(
        "NEXT_PUBLIC_SUPABASE_URL", ""
    )
    key = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get(
        "NEXT_PUBLIC_SUPABASE_ANON_KEY", ""
    )

    if not url or not key:
        raise SystemExit(
            "Missing Supabase credentials. Set SUPABASE_URL and "
            "SUPABASE_ANON_KEY, or provide frontend/.env.local."
        )

    return url.rstrip("/"), key


def ping(table: str = DEFAULT_TABLE) -> str:
    """Hit the REST endpoint and return the raw JSON response body."""
    base_url, key = resolve_credentials()
    endpoint = f"{base_url}/rest/v1/{table}?select=*&limit=1"

    req = request.Request(
        endpoint,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        },
    )

    try:
        with request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8")
    except error.HTTPError as exc:
        raise SystemExit(
            f"Supabase returned HTTP {exc.code} for '{table}'. If RLS is enabled, "
            f"apply schema_sql/supabase_keep_alive_policy.sql to allow anon SELECT."
        ) from exc
    except error.URLError as exc:
        raise SystemExit(f"Could not reach Supabase: {exc.reason}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=f"Table to read from (default: {DEFAULT_TABLE}).",
    )
    args = parser.parse_args()

    try:
        body = ping(args.table)
    except SystemExit as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Supabase responded from '{args.table}': {body}")
    print("Heartbeat OK - database activity recorded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
