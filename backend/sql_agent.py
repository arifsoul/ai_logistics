"""Text-to-SQL over the `orders` table.

Flow: retrieve schema metadata from pgvector -> LLM writes one SELECT ->
guardrails -> execute read-only -> LLM narrates the result. The API returns the
SQL, the table, a chart spec and the narration so the UI can render all three.

Safety: the statement runs inside a READ ONLY transaction with a statement
timeout, so even a wrong or hostile query cannot write or hang the database.
"""

import json
import random
import re
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.ai_config import effective_ai_model, openai_client
from backend.database import SQL_TIMEOUT_MS, SessionLocal
from backend.ddl_docs import DDL_REF, cached_ddl
from backend.schema_docs import DDL as COMPACT_DDL
from backend.vectorstore import get_doc, schema_context

MAX_ROWS = 200


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    if any(s in msg for s in ["503", "429", "500", "502", "504", "unavailable", "high demand", "overloaded", "rate limit"]):
        return True
    sc = getattr(exc, "status_code", None)
    if sc in (429, 500, 502, 503, 504):
        return True
    resp = getattr(exc, "response", None)
    if resp is not None and getattr(resp, "status_code", None) in (429, 500, 502, 503, 504):
        return True
    return False


def _call_with_retry(fn, retries: int = 3, base: float = 1.0):
    last: Exception | None = None
    for i in range(retries):
        try:
            return fn()
        except Exception as e:
            last = e
            if not _is_retryable(e) or i == retries - 1:
                raise
            time.sleep(base * (2**i) + random.uniform(0, 0.5))
    raise last  # type: ignore


# Words that must never appear in generated SQL. The read-only transaction is
# the real enforcement; this is a cheap early reject with a clear message.
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|copy|"
    r"vacuum|merge|call|do|reindex|refresh|listen|notify|lock|cluster|"
    r"pg_sleep|pg_read_file|pg_ls_dir|lo_import|lo_export|dblink|"
    r"pg_terminate_backend|current_setting|set_config)\b",
    re.IGNORECASE,
)

SQL_PROMPT = """You write PostgreSQL for a logistics analytics database.

The schema below is generated from the live database. The column comments list
the real values, so filter on those literals and never invent one.

```sql
{ddl}
```

{context}

Rules:
- Emit exactly ONE read-only SELECT (a leading CTE with WITH is fine). Nothing else.
- Only the `orders` table exists. Never reference another table.
- Never write INSERT/UPDATE/DELETE/DDL.
- Use only the columns and values documented above. If the question cannot be
  answered from this table, emit only: NO_SQL
- For grouped results name the grouping column `label` and the measure `value`,
  so the UI can chart it. For a single scalar, name the column after the metric.
- Order time series chronologically; order rankings by value DESC.
- Return raw SQL only: no markdown fence, no explanation, no trailing semicolon.

Question: {question}"""

ANSWER_PROMPT = """You are a logistics analyst. Describe ONLY the query result
below. It is the complete answer; you have no other data.

Hard rules:
- Every number you write must appear in the result. Never estimate, extrapolate
  or add outside knowledge.
- If the result is empty, say that no rows matched and stop.
- 2-4 sentences. Quote the concrete numbers, name the top and bottom entries for
  a ranking, state the direction of the trend for a time series.
- Do not mention SQL, tables or columns. No markdown headings.

Question: {question}
Query result (JSON): {result}"""


class SqlAgentError(Exception):
    """Generated SQL was rejected or failed to execute."""


def _strip_fence(sql: str) -> str:
    """Remove a ```sql ... ``` wrapper if the model added one."""
    sql = sql.strip()
    if sql.startswith("```"):
        sql = re.sub(r"^```[a-zA-Z]*\n?", "", sql)
        sql = re.sub(r"```$", "", sql).strip()
    return sql.rstrip(";").strip()


def sanitize_sql(sql: str) -> str:
    """Validate one read-only SELECT and cap the row count. Raises on refusal."""
    sql = _strip_fence(sql)
    if not sql:
        raise SqlAgentError("The model returned no SQL.")
    if sql.upper().startswith("NO_SQL"):
        # The planner is told to emit this instead of guessing at a question the
        # table cannot answer.
        raise SqlAgentError(
            "That question cannot be answered from the orders data."
        )
    if ";" in sql:
        raise SqlAgentError("Only a single SQL statement is allowed.")
    if not re.match(r"^(select|with)\b", sql, re.IGNORECASE):
        raise SqlAgentError("Only SELECT queries are allowed.")
    found = FORBIDDEN.search(sql)
    if found:
        raise SqlAgentError(f"Disallowed SQL keyword: {found.group(0)}")
    if not re.search(r"\blimit\s+\d+\s*$", sql, re.IGNORECASE):
        sql = f"{sql} LIMIT {MAX_ROWS}"
    return sql


def run_sql(sql: str, db: Optional[Session] = None) -> Dict[str, Any]:
    """Execute vetted SQL read-only. Returns `{columns, rows}`."""
    session = db or SessionLocal()
    try:
        session.rollback()  # start a fresh transaction
        session.execute(text("SET TRANSACTION READ ONLY"))
        session.execute(text(f"SET LOCAL statement_timeout = {SQL_TIMEOUT_MS}"))
        result = session.execute(text(sql))
        columns = list(result.keys())
        rows = [[_jsonable(value) for value in row] for row in result.fetchall()]
        return {"columns": columns, "rows": rows}
    finally:
        session.rollback()
        if db is None:
            session.close()


def _jsonable(value: Any) -> Any:
    """Dates and Decimals are not JSON-serializable; everything else passes."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return float(value) if hasattr(value, "as_integer_ratio") else str(value)


TEMPORAL_LABEL = re.compile(r"^\d{4}-(\d{2}|W\d{2}|\d{2}-\d{2})$", re.IGNORECASE)


def build_chart(columns: List[str], rows: List[List[Any]]) -> Optional[Dict[str, Any]]:
    """Chart spec for a label/value shaped result, else None.

    A chart needs at least two rows, one text label column and one numeric
    measure. Chronological labels get a line, everything else a bar.
    """
    if len(rows) < 2 or len(columns) < 2:
        return None

    label_index = next(
        (i for i, _ in enumerate(columns) if all(isinstance(r[i], str) for r in rows)),
        None,
    )
    value_index = next(
        (
            i
            for i, _ in enumerate(columns)
            if i != label_index
            and all(isinstance(r[i], (int, float)) and not isinstance(r[i], bool) for r in rows)
        ),
        None,
    )
    if label_index is None or value_index is None:
        return None

    labels = [row[label_index] for row in rows]
    is_time = all(TEMPORAL_LABEL.match(label) for label in labels)
    return {
        "type": "line" if is_time else "bar",
        "label": columns[value_index],
        "labels": labels,
        "values": [row[value_index] for row in rows],
    }


def generate_sql(question: str, db: Session, model: Optional[str] = None, base_url: Optional[str] = None) -> str:
    """Ask the LLM for SQL grounded in the generated DDL and retrieved metadata."""
    # The annotated DDL is always in the prompt; retrieval only adds the column
    # docs and exemplars that match the question.
    ddl = get_doc(db, DDL_REF) or cached_ddl() or COMPACT_DDL
    prompt = SQL_PROMPT.format(
        ddl=ddl,
        context=schema_context(db, question, exclude=DDL_REF),
        question=question,
    )
    response = _call_with_retry(
        lambda: openai_client(base_url=base_url).chat.completions.create(
            model=model or effective_ai_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
    )
    return sanitize_sql(response.choices[0].message.content or "")


# Forward-looking questions cannot be answered by SQL over past rows, so they go
# to the deterministic moving-average forecaster instead of the SQL planner.
FORECAST_RE = re.compile(
    r"\b(predict|forecast|projection|prediksi|proyeksi|ramalan|perkiraan|restock|"
    r"reorder|inventory|stok)\b",
    re.IGNORECASE,
)
SKU_RE = re.compile(r"\b([A-Za-z]+-\d{4})\b")
HORIZON_RE = re.compile(r"(\d+)\s*(?:months?|bulan)", re.IGNORECASE)


def forecast_frames(question: str) -> Optional[List[Dict[str, Any]]]:
    """Frames for a forecast question, or None when it is not one."""
    if not FORECAST_RE.search(question):
        return None
    sku = SKU_RE.search(question)
    if not sku:
        return None

    from backend.analytics import LogisticsAnalytics

    horizon = HORIZON_RE.search(question)
    result = LogisticsAnalytics().forecast(
        sku.group(1).upper(), int(horizon.group(1)) if horizon else 4
    )
    history = [[row["period"], row["value"], "actual"] for row in result["historical"]]
    projection = [[row["period"], row["value"], "forecast"] for row in result["forecast"]]
    rows = history + projection
    return [
        {"type": "table", "columns": ["period", "quantity", "kind"], "rows": rows},
        {
            "type": "chart",
            "chart": {
                "type": "line",
                "label": f"{result['sku']} quantity",
                "labels": [row[0] for row in rows],
                "values": [row[1] for row in rows],
            },
        },
        {"type": "meta", "forecast": result},
    ]


async def answer(
    question: str,
    db: Optional[Session] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """NDJSON-ready frames: sql/table/chart/meta, then answer tokens, then done.

    Frame types: `sql`, `table`, `chart`, `meta`, `token`, `error`, `done`.
    """
    session = db or SessionLocal()
    try:
        frames: List[Dict[str, Any]] = []
        try:
            forecast = forecast_frames(question)
            if forecast is not None:
                frames = forecast
            else:
                sql = generate_sql(question, session, model, base_url)
                table = run_sql(sql, session)
                frames = [
                    {"type": "sql", "sql": sql},
                    {"type": "table", **table},
                ]
                chart = build_chart(table["columns"], table["rows"])
                if chart:
                    frames.append({"type": "chart", "chart": chart})
                # Explainability: query plan + row count + columns for UI
                frames.append({"type": "meta", "interpretation": {"sql": sql, "row_count": len(table["rows"]), "columns": table["columns"]}})
        except (SqlAgentError, ValueError) as error:
            yield {"type": "error", "message": str(error)}
            return
        except Exception as error:  # database or provider failure
            yield {"type": "error", "message": f"Query failed: {error}"}
            return

        for frame in frames:
            yield frame

        payload = next(frame for frame in frames if frame["type"] == "table")
        prompt = ANSWER_PROMPT.format(
            question=question,
            # Keep the prompt bounded; the table itself is already in the UI.
            result=json.dumps({"columns": payload["columns"], "rows": payload["rows"]})[
                :6000
            ],
        )
        stream = _call_with_retry(
            lambda: openai_client(base_url=base_url).chat.completions.create(
                model=model or effective_ai_model(),
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
        )
        for chunk in stream:
            token = chunk.choices[0].delta.content if chunk.choices else None
            if token:
                yield {"type": "token", "text": token}
        yield {"type": "done"}
    finally:
        if db is None:
            session.close()
