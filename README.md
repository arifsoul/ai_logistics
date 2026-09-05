---
title: Logistics Analytics API
emoji: 📦
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
app_port: 7860
---

# Logistics Analytics — text-to-SQL over Postgres

Ask the logistics database in plain language. Every question is translated into
SQL, executed against Postgres, and answered with a narrative, a table and a
chart. `mock_logistics_data.csv` is the single source of truth: it is seeded into
Postgres, and nothing else feeds the answers.

- **API** — FastAPI, API-only (no server-rendered HTML).
- **UI** — Next.js app in `frontend/`, deployed to Netlify.
- **Data** — Postgres (Supabase in production) + `pgvector`.
- **Retrieval** — pgvector stores *schema metadata only*, so the model knows the
  columns and their allowed values before it writes SQL. There is no document
  upload and no Chroma.

## Layout

```
app.py                    dev entry point for the API
mock_logistics_data.csv   source of truth, 400 orders
backend/
  main.py                 FastAPI routes (chat, analytics, auth, history)
  database.py             engine/session from DATABASE_URL
  models_db.py            User, ChatSession, ChatMessage, Order, SchemaDoc
  seed.py                 CSV -> orders, schema docs -> pgvector
  schema_docs.py          the 24 metadata documents that get embedded
  vectorstore.py          pgvector cosine search
  sql_agent.py            question -> SQL -> narrative + table + chart frames
  analytics.py            fixed KPI/chart queries (pure SQL)
  history.py              chat turns persisted in Postgres
frontend/                 Next.js frontend
tests/                    21 unittest tests
```

## Prerequisites

- Python 3.11+
- Node 20+
- A Postgres 15+ database with the `vector` extension available

## 1. Database

Production is Supabase; `pgvector` is already available there. For local work,
one container is enough:

```powershell
docker run -d --name pgvec -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=logistics -p 55432:5432 pgvector/pgvector:pg17
```

## 2. Backend

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # then fill in API_KEY and DATABASE_URL
python -m backend.seed
python app.py
```

`python -m backend.seed` creates the extension and tables, loads the CSV and
embeds the schema metadata. Expect:

```
orders: 400 rows loaded
schema_docs: 24 documents embedded
```

Re-running it is safe — `orders` is truncated and reloaded, `schema_docs` is
replaced. Add `--no-vectors` to load the orders without spending embedding
calls. The API then listens on <http://127.0.0.1:8000> (`/docs` for the OpenAPI
page).

> Use `127.0.0.1` rather than `localhost` in `DATABASE_URL` on Windows; the IPv6
> lookup for `localhost` can add ~26 s to every connection.

## 3. Frontend

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev
```

Open <http://localhost:3000>. It redirects to `/chat`, which is the only place
questions are asked. Register an account on first use.

| Route | Purpose |
| --- | --- |
| `/chat` | Ask anything. Streams narrative + table + chart, keeps history. |
| `/dashboard` | Fixed KPI cards and charts only — no input fields. |
| `/admin` | User list, create user, change role. Admins only. |

## Environment variables

Backend (`.env`, read by `backend/ai_config.py` and `backend/database.py`):

| Variable | Notes |
| --- | --- |
| `API_KEY` | Key for the AI provider. Google AI Studio: <https://aistudio.google.com/apikey> |
| `AI_BASE_URL` | Any OpenAI-compatible base URL. Defaults to Google AI Studio. |
| `AI_MODEL` | Default chat model, e.g. `gemini-flash-latest`. The chat UI can override per request. |
| `EMBEDDING_MODEL` | Embedding model for the schema metadata, e.g. `gemini-embedding-001`. |
| `EMBEDDING_DIM` | Vector width of that model. `3072` for `gemini-embedding-001`. Changing it requires a re-seed. |
| `DATABASE_URL` | `postgresql+psycopg://...` — the driver must be psycopg 3. |
| `SQL_TIMEOUT_MS` | Hard ceiling on any generated query. Default `5000`. |
| `CORS_ORIGINS` | Comma-separated browser origins allowed to call the API. |
| `SECRET_KEY` | JWT signing secret. Set a long random value in production. |
| `SUPER_USERNAME`, `SUPER_PASSWORD` | Optional initial superadmin, applied on startup. |

Frontend (`frontend/.env.local`):

| Variable | Notes |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | Origin of the API. Defaults to `http://127.0.0.1:8000`. |

## How a question is answered

1. The question is embedded and matched against the schema metadata in
   `pgvector`, which yields the relevant columns and their real values.
2. The model writes one `SELECT`. `backend/sql_agent.py` rejects anything else,
   forces a `LIMIT`, and applies `SQL_TIMEOUT_MS`.
3. Postgres executes it. The rows — not the model — are the numbers.
4. The API streams NDJSON frames (`sql`, `table`, `chart`, `token`, `meta`,
   `done`) so the UI fills in as the answer arrives.
5. Both turns are written to `chat_messages`, so reloading `/chat` replays the
   exact same narrative, table and chart.

Stock questions ("prediksi stok SKU-x untuk 4 bulan") take a separate path: a
three-month moving average with a 15% safety buffer, returned as actual +
forecast rows.

## Tests

```powershell
python -W ignore::ResourceWarning -m unittest discover -s tests
```

21 tests. They stub the AI provider, so no API key or network access is needed.

## Deploy

**Backend — Hugging Face Spaces (Docker)** — repo ini siap deploy sebagai Space Docker:

1. Buat Space baru di https://huggingface.co/new-space → SDK `Docker` → `Blank`.
2. Push repo ini ke Space (`git push` ke `https://huggingface.co/spaces/<user>/<space>`). HF build `Dockerfile` otomatis, expose `7860`.
3. Di Space **Settings → Variables and secrets**, set:
   ```
   DATABASE_URL=postgresql+psycopg://... (Supabase pooler)
   API_KEY=<google_ai_studio_key>
   AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
   AI_MODEL=gemini-flash-latest
   EMBEDDING_MODEL=gemini-embedding-001
   EMBEDDING_DIM=3072
   SECRET_KEY=<random_long>
   CORS_ORIGINS=https://<your-netlify>.netlify.app,https://<user>-<space>.hf.space
   SUPER_USERNAME=admin
   SUPER_PASSWORD=admin
   ```
4. Seed sekali ke Supabase: `DATABASE_URL=<supabase> python -m backend.seed`
5. Space URL jadi `NEXT_PUBLIC_API_URL` untuk frontend. Health check: `GET /` dan `/docs`.

`Dockerfile` jalankan `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` (`$PORT=7860` di HF). Frontmatter `sdk: docker` + `app_port: 7860` sudah di `README.md`.

**Backend — alternatif (Render / host lain)** — host ASGI apapun:

```
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Run `python -m backend.seed` sekali ke Supabase. Tambah origin frontend ke `CORS_ORIGINS`.

**Frontend** — Netlify pick up `frontend/netlify.toml` (base `frontend`, `@netlify/plugin-nextjs`). Set `NEXT_PUBLIC_API_URL` di Netlify ke origin API (HF Space URL atau Render URL).

## Assumptions and limitations

- On-time rate is `delivered / (delivered + delayed)`; in-transit, exception and
  canceled orders are excluded.
- Average delivery days uses delivered rows that have both dates.
- Forecasting is a planning baseline, not an inventory optimizer.
- The API has no rate limiting. Put it behind a gateway if it is public.
- Generated SQL is restricted to a single read-only `SELECT` on `orders`, but the
  database user should still be read-only in production.
