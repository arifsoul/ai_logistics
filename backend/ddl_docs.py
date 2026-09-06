"""Annotated DDL for `orders`, generated from live Postgres introspection.

This is the RAG context for text-to-SQL. Nothing here is hand-maintained:

- column names, types, nullability and the primary key come from
  `information_schema`;
- every text column's distinct values are re-read on each sync, so a new
  carrier or status becomes part of the context by itself;
- the per-column purpose comment is written once by the LLM and cached on disk,
  because a column's meaning does not change when its data does.

The output is one `CREATE TABLE` + `COMMENT ON ...` script saved to
`schema_sql/orders.sql` and embedded into pgvector.

    python -m backend.ddl_docs            # sync, reusing cached comments
    python -m backend.ddl_docs --force    # regenerate the comments too
    python -m backend.ddl_docs --no-llm   # use the fallback descriptions
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.schema_docs import COLUMNS as FALLBACK_COLUMNS
from backend.schema_docs import EXAMPLES, OVERVIEW, TABLE_NAME

TABLE = TABLE_NAME
DDL_REF = f"ddl:{TABLE}"

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "schema_sql"
SQL_FILE = SQL_DIR / f"{TABLE}.sql"
COMMENT_CACHE = SQL_DIR / f"{TABLE}.comments.json"

# A text column with at most this many distinct values gets them listed in its
# comment; above the cap only the count is recorded, so 355 SKUs do not eat the
# prompt budget.
MAX_UNIQUE_VALUES = int(os.getenv("MAX_UNIQUE_VALUES", "50"))

# information_schema returns real identifiers, but they are interpolated into
# SQL, so re-check them before use.
IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
TEXT_TYPES = {"character varying", "text", "character"}


class DdlError(Exception):
    """Introspection found nothing to describe."""


def _quote(identifier: str) -> str:
    if not IDENT.match(identifier):
        raise DdlError(f"Unsafe identifier: {identifier!r}")
    return f'"{identifier}"'


def columns(db: Session) -> List[Dict[str, Any]]:
    """Live column definitions for `orders`, in ordinal order."""
    rows = db.execute(
        text(
            """
            SELECT column_name, data_type, is_nullable, column_default,
                   character_maximum_length, numeric_precision, numeric_scale
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :table
            ORDER BY ordinal_position
            """
        ),
        {"table": TABLE},
    ).mappings()
    result = [dict(row) for row in rows]
    if not result:
        raise DdlError(f"Table {TABLE} not found. Run `python -m backend.seed`.")
    return result


def primary_key(db: Session) -> List[str]:
    rows = db.execute(
        text(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON kcu.constraint_name = tc.constraint_name
             AND kcu.table_schema = tc.table_schema
            WHERE tc.table_schema = 'public' AND tc.table_name = :table
              AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position
            """
        ),
        {"table": TABLE},
    )
    return [row[0] for row in rows]


def sql_type(column: Dict[str, Any]) -> str:
    """`information_schema` parts rendered back into a DDL type."""
    data_type = column["data_type"]
    if data_type == "numeric" and column["numeric_precision"]:
        return f"numeric({column['numeric_precision']},{column['numeric_scale']})"
    if data_type == "character varying" and column["character_maximum_length"]:
        return f"varchar({column['character_maximum_length']})"
    return data_type


def sample_values(db: Session, column: str) -> Tuple[List[str], int]:
    """`(values, distinct_count)`. `values` is empty above MAX_UNIQUE_VALUES."""
    quoted = _quote(column)
    count = db.execute(
        text(f"SELECT COUNT(DISTINCT {quoted}) FROM {_quote(TABLE)}")
    ).scalar_one()
    if not count or count > MAX_UNIQUE_VALUES:
        return [], int(count or 0)
    rows = db.execute(
        text(
            f"SELECT DISTINCT {quoted} FROM {_quote(TABLE)}"
            f" WHERE {quoted} IS NOT NULL ORDER BY 1"
        )
    )
    return [str(row[0]) for row in rows], int(count)


def collect_samples(db: Session, cols: List[Dict[str, Any]]) -> Dict[str, Tuple[List[str], int]]:
    """Distinct values per text column. Numeric and date columns are skipped."""
    return {
        column["column_name"]: sample_values(db, column["column_name"])
        for column in cols
        if column["data_type"] in TEXT_TYPES
    }


COMMENT_PROMPT = """You document PostgreSQL schemas. Describe the table below
and every one of its columns in English.

Table DDL:
```sql
{ddl}
```

Sample values:
{samples}

Rules:
- `table_comment`: one sentence on the table's purpose. Do not name columns.
- `column_comments`: one key per column listed below, value = one sentence on
  what the column holds and how it is used in analytics.
- Columns: {column_list}
- Reply with a single JSON object and nothing else.

{{"table_comment": "...", "column_comments": {{"col": "..."}}}}"""


def _samples_block(samples: Dict[str, Tuple[List[str], int]]) -> str:
    lines = [
        f"- {name}: {', '.join(values)}"
        for name, (values, _) in samples.items()
        if values
    ]
    return "\n".join(lines) or "(none)"


def llm_comments(
    bare_ddl: str,
    cols: List[Dict[str, Any]],
    samples: Dict[str, Tuple[List[str], int]],
    model: Optional[str] = None,
) -> Dict[str, str]:
    """`{"__table__": ..., "<column>": ...}` from the LLM. Raises on failure."""
    from backend.ai_config import effective_ai_model, openai_client

    names = [column["column_name"] for column in cols]
    prompt = COMMENT_PROMPT.format(
        ddl=bare_ddl,
        samples=_samples_block(samples),
        column_list=", ".join(names),
    )
    response = openai_client().chat.completions.create(
        model=model or effective_ai_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return parse_comments(response.choices[0].message.content or "", names)


def parse_comments(raw: str, names: List[str]) -> Dict[str, str]:
    """Pull the comment map out of an LLM reply, fenced or not."""
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise DdlError("The model returned no JSON.")
    data = json.loads(match.group(0))
    comments = data.get("column_comments") or {}
    if not isinstance(comments, dict) or not comments:
        raise DdlError("The model returned no column comments.")
    result = {"__table__": str(data.get("table_comment") or OVERVIEW)}
    for name in names:
        value = comments.get(name)
        if value:
            result[name] = str(value)
    return result


def fallback_comments(cols: List[Dict[str, Any]]) -> Dict[str, str]:
    """Hand-written descriptions, used when the LLM is unavailable."""
    comments = {"__table__": OVERVIEW}
    for column in cols:
        name = column["column_name"]
        # Strip the type prefix from the hand-written text: the DDL already
        # states the type, so repeating it wastes prompt space.
        described = FALLBACK_COLUMNS.get(name, f"Column {name}.")
        comments[name] = re.sub(r"^[A-Z]+(\([^)]*\))?,?\s*", "", described)
    return comments


def load_cached_comments() -> Dict[str, str]:
    if not COMMENT_CACHE.exists():
        return {}
    try:
        return json.loads(COMMENT_CACHE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_cached_comments(comments: Dict[str, str]) -> None:
    SQL_DIR.mkdir(parents=True, exist_ok=True)
    COMMENT_CACHE.write_text(
        json.dumps(comments, indent=2, sort_keys=True), encoding="utf-8"
    )


def resolve_comments(
    bare_ddl: str,
    cols: List[Dict[str, Any]],
    samples: Dict[str, Tuple[List[str], int]],
    force: bool = False,
    use_llm: bool = True,
    model: Optional[str] = None,
) -> Dict[str, str]:
    """Cached comments when they still cover every column, else regenerate."""
    names = [column["column_name"] for column in cols]
    cached = {} if force else load_cached_comments()
    if all(name in cached for name in names) and "__table__" in cached:
        return cached

    if use_llm:
        try:
            comments = llm_comments(bare_ddl, cols, samples, model)
        except Exception as error:  # provider down, quota, bad JSON
            print(f"comment generation failed ({error}); using fallback text")
            comments = fallback_comments(cols)
        else:
            # Fill any column the model skipped so the DDL is never partial.
            for name, described in fallback_comments(cols).items():
                comments.setdefault(name, described)
    else:
        comments = fallback_comments(cols)

    save_cached_comments(comments)
    return comments


def _value_note(values: List[str], count: int) -> str:
    if values:
        listed = ", ".join(f"'{value}'" for value in values)
        return f" {count} distinct values: {listed}."
    return f" {count} distinct values (too many to list)." if count else ""


def build_ddl(
    cols: List[Dict[str, Any]],
    pk: List[str],
    comments: Dict[str, str],
    samples: Dict[str, Tuple[List[str], int]],
) -> str:
    """The annotated `CREATE TABLE` + `COMMENT ON ...` script."""
    lines = []
    for column in cols:
        parts = [f"  {column['column_name']} {sql_type(column)}"]
        if column["is_nullable"] == "NO":
            parts.append(" NOT NULL")
        if column["column_default"]:
            parts.append(f" DEFAULT {column['column_default']}")
        lines.append("".join(parts))
    if pk:
        lines.append(f"  PRIMARY KEY ({', '.join(pk)})")

    ddl = f"CREATE TABLE {TABLE} (\n" + ",\n".join(lines) + "\n);"

    table_comment = comments.get("__table__", OVERVIEW).replace("'", "''")
    statements = [f"COMMENT ON TABLE {TABLE} IS '{table_comment}';"]
    for column in cols:
        name = column["column_name"]
        note = comments.get(name, f"Column {name}.")
        values, count = samples.get(name, ([], 0))
        body = (note.rstrip() + _value_note(values, count)).replace("'", "''")
        statements.append(f"COMMENT ON COLUMN {TABLE}.{name} IS '{body}';")

    return (
        "-- Generated by backend/ddl_docs.py from live Postgres introspection.\n"
        "-- Do not edit by hand: `python -m backend.ddl_docs` rewrites it.\n\n"
        f"{ddl}\n\n-- Comments\n" + "\n".join(statements) + "\n"
    )


def build_docs(
    ddl: str,
    cols: List[Dict[str, Any]],
    comments: Dict[str, str],
    samples: Dict[str, Tuple[List[str], int]],
) -> Dict[str, str]:
    """`ref -> text` for pgvector: the whole DDL, one doc per column, examples.

    The DDL doc is always injected into the prompt; the per-column docs exist so
    retrieval can surface the columns a question actually mentions.
    """
    docs = {DDL_REF: ddl}
    for column in cols:
        name = column["column_name"]
        values, count = samples.get(name, ([], 0))
        docs[f"{TABLE}.{name}"] = (
            f"{TABLE}.{name} {sql_type(column)} — "
            f"{comments.get(name, '')}{_value_note(values, count)}"
        )
    docs.update({f"example:{name}": body for name, body in EXAMPLES.items()})
    return docs


def cached_ddl() -> Optional[str]:
    """The last generated DDL from disk, for a cold vector store."""
    try:
        return SQL_FILE.read_text(encoding="utf-8")
    except OSError:
        return None


def sync(
    db: Session,
    force: bool = False,
    use_llm: bool = True,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Refresh `schema_sql/orders.sql` and pgvector. Cheap when nothing moved.

    Re-embedding only happens when the generated DDL text differs from what is
    already stored, so calling this on every boot costs a handful of small
    queries and no API calls.
    """
    from backend.models_db import SchemaDoc
    from backend.vectorstore import replace_schema_docs

    cols = columns(db)
    pk = primary_key(db)
    samples = collect_samples(db, cols)

    bare = f"CREATE TABLE {TABLE} (\n" + ",\n".join(
        f"  {column['column_name']} {sql_type(column)}" for column in cols
    ) + "\n);"
    comments = resolve_comments(bare, cols, samples, force, use_llm, model)

    ddl = build_ddl(cols, pk, comments, samples)
    SQL_DIR.mkdir(parents=True, exist_ok=True)
    SQL_FILE.write_text(ddl, encoding="utf-8")

    stored = db.query(SchemaDoc).filter(SchemaDoc.ref == DDL_REF).first()
    if stored is not None and stored.content == ddl and not force:
        return {"changed": False, "documents": 0, "sql_file": str(SQL_FILE)}

    docs = build_docs(ddl, cols, comments, samples)
    count = replace_schema_docs(db, docs)
    return {"changed": True, "documents": count, "sql_file": str(SQL_FILE)}


def main() -> int:
    from backend.database import SessionLocal

    parser = argparse.ArgumentParser(description="Refresh the orders DDL context.")
    parser.add_argument(
        "--force", action="store_true", help="regenerate comments and re-embed"
    )
    parser.add_argument(
        "--no-llm", action="store_true", help="use the built-in descriptions"
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = sync(db, force=args.force, use_llm=not args.no_llm)
    finally:
        db.close()

    print(f"schema_sql: {result['sql_file']}")
    if result["changed"]:
        print(f"pgvector: {result['documents']} documents embedded")
    else:
        print("pgvector: unchanged, nothing re-embedded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
